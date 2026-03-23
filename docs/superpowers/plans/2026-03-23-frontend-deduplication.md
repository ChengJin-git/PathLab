# Frontend Deduplication Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate ~1,400 lines of redundant frontend code by extracting 4 shared primitives and migrating 47 files to use them — zero behaviour change.

**Architecture:** Four new primitives (ModalShell, useDebounce, useConfirmDialog, PaginationFooter) are created first as pure additions, then consumed by existing files via targeted migration. All changes are verifiable with `lsp_diagnostics` + grep success criteria.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, react-i18next, Electron (renderer process)

**Spec:** `docs/superpowers/specs/2026-03-23-frontend-deduplication-design.md`

**Base path (all relative paths below are inside):** `pathlab/pathlab-client/src/renderer/src/`

**Existing helpers to know:**
- `lib/utils.ts` exports `cn(...)` (classname merge utility — already exists, not new)
- `lib/useAsyncAction.ts` — already exists; signature: `useAsyncAction<T>(options?: { onError?: (err: unknown) => void }): [isPending: boolean, run: (fn: () => Promise<T>) => Promise<T | undefined>]`
- `components/settings/ConfirmDialog.tsx` exports `ConfirmDialogState`, `ShowConfirmDialog`, `ConfirmDialog` component, `ConfirmDialogProps`

**lsp_diagnostics invocation:** use the `lsp_diagnostics` tool with `filePath` set to the absolute file path and `severity: "error"` — expect 0 errors.

---

## File Map

**New files (create):**
- `lib/useDebounce.ts`
- `lib/useConfirmDialog.ts`
- `components/ui/modal-shell.tsx`
- `components/ui/pagination-footer.tsx`

**Modified files (migrate):**
- 21 modal files → ModalShell (Tasks 2–4)
- 2 files → useDebounce (Task 5)
- 12 files → useConfirmDialog (Tasks 6–7, includes `UsersTab.tsx` as PermissionCenterModal's parent)
- 26 files → useAsyncAction (Tasks 8–10)
- 6 files → PaginationFooter (Task 11)

---

## Task 1: Create the 4 New Primitives

**Files:**
- Create: `lib/useDebounce.ts`
- Create: `lib/useConfirmDialog.ts`
- Create: `components/ui/modal-shell.tsx`
- Create: `components/ui/pagination-footer.tsx`

- [ ] **Step 1: Create `lib/useDebounce.ts`**

```typescript
import { useState, useEffect } from 'react'

export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedValue(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debouncedValue
}
```

- [ ] **Step 2: Create `lib/useConfirmDialog.ts`**

```typescript
import { useState } from 'react'
import type { ConfirmDialogState, ShowConfirmDialog } from '../components/settings/ConfirmDialog'

const CLOSED: ConfirmDialogState = {
  isOpen: false,
  title: '',
  message: '',
  onConfirm: () => {},
}

export function useConfirmDialog() {
  const [dialogState, setDialogState] = useState<ConfirmDialogState>(CLOSED)

  const showConfirmDialog: ShowConfirmDialog = (config) => {
    setDialogState({ isOpen: true, ...config })
  }

  const closeConfirmDialog = () => {
    setDialogState(CLOSED)
  }

  return { dialogState, showConfirmDialog, closeConfirmDialog }
}
```

- [ ] **Step 3: Create `components/ui/modal-shell.tsx`**

```typescript
import React, { useEffect } from 'react'
import { cn } from '../../lib/utils'

interface ModalShellProps {
  isOpen: boolean
  onClose?: () => void
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '6xl'
  className?: string
  children: React.ReactNode
}

const MAX_WIDTH: Record<string, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '6xl': 'max-w-6xl',
}

export function ModalShell({
  isOpen,
  onClose,
  maxWidth = 'md',
  className,
  children,
}: ModalShellProps) {
  useEffect(() => {
    if (!onClose) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-2 sm:p-4 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className={cn(
          'bg-white rounded-xl sm:rounded-2xl shadow-2xl w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto',
          MAX_WIDTH[maxWidth] ?? 'max-w-md',
          className
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create `components/ui/pagination-footer.tsx`**

```typescript
import React from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from './button'
import { Select } from './select'

const DEFAULT_PAGE_SIZE_OPTIONS = ['4', '6', '9', '18']

interface PaginationFooterProps {
  page: number
  pageSize: number
  total: number
  disabled?: boolean
  pageSizeOptions?: string[]
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
}

export function PaginationFooter({
  page,
  pageSize,
  total,
  disabled,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  onPageChange,
  onPageSizeChange,
}: PaginationFooterProps) {
  const { t } = useTranslation()
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1)

  return (
    <div className="flex flex-col gap-3 border-t border-gray-200 pt-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <span>{t('settings.permissionCenterModal.itemsPerPage')}</span>
        <Select
          value={String(pageSize)}
          onChange={(value) => onPageSizeChange(Number(value))}
          options={pageSizeOptions.map((value) => ({ value, label: value }))}
          className="w-20"
          disabled={disabled}
        />
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <span className="text-sm text-gray-500">
          {t('settings.permissionCenterModal.pageInfo', {
            current: Math.min(page, totalPages),
            total: totalPages,
            count: total,
          })}
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={disabled || page <= 1}
            className="gap-1"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            {t('settings.permissionCenterModal.previous')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={disabled || page >= totalPages}
            className="gap-1"
          >
            {t('settings.permissionCenterModal.next')}
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Verify lsp_diagnostics (severity: error) on all 4 new files — expect 0 errors each**

Run `lsp_diagnostics` with `severity: "error"` on:
- Absolute path: `.../src/renderer/src/lib/useDebounce.ts`
- Absolute path: `.../src/renderer/src/lib/useConfirmDialog.ts`
- Absolute path: `.../src/renderer/src/components/ui/modal-shell.tsx`
- Absolute path: `.../src/renderer/src/components/ui/pagination-footer.tsx`

- [ ] **Step 6: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/lib/useDebounce.ts \
        pathlab/pathlab-client/src/renderer/src/lib/useConfirmDialog.ts \
        pathlab/pathlab-client/src/renderer/src/components/ui/modal-shell.tsx \
        pathlab/pathlab-client/src/renderer/src/components/ui/pagination-footer.tsx
git commit -m "refactor: add ModalShell, useDebounce, useConfirmDialog, PaginationFooter primitives"
```

---

## Task 2: Migrate ModalShell — Root Components (5 files)

**Files to modify:**
- `components/ChangePasswordModal.tsx` (maxWidth="md", onClose=yes)
- `components/SetEmailModal.tsx` (maxWidth="md", onClose=yes)
- `components/DisclaimerModal.tsx` (maxWidth="xl", onClose=no)
- `components/MaintenanceNoticeModal.tsx` (maxWidth="lg", onClose=no)
- `components/RegisterRequestModal.tsx` (maxWidth="md", onClose=no)

**Migration pattern for each file:**

1. Add import: `import { ModalShell } from './ui/modal-shell'`
2. Find the outermost `<div className="fixed inset-0 ...">` — this is the backdrop div
3. Find the matching inner white-box div (`<div className="bg-white rounded-...">`), which is a direct child
4. Replace **both** the outer (backdrop) div and the inner (white box) div with a single `<ModalShell>` open tag
5. The remaining children (header, form, buttons etc.) become `ModalShell`'s children
6. If the file has `onClose`=yes: use `<ModalShell isOpen={isOpen} onClose={onClose} maxWidth="...">`
7. If the file has `onClose`=no: use `<ModalShell isOpen={isOpen} maxWidth="...">`
8. Remove the now-redundant `isOpen ? ... : null` guard around the outer div (ModalShell handles this internally with `if (!isOpen) return null`)

- [ ] **Step 1: Read + migrate `components/ChangePasswordModal.tsx`**

- [ ] **Step 2: Run lsp_diagnostics (severity: error) on ChangePasswordModal.tsx — expect 0 errors**

- [ ] **Step 3: Read + migrate `components/SetEmailModal.tsx`** — maxWidth="md", onClose={onClose}

- [ ] **Step 4: Run lsp_diagnostics (severity: error) — expect 0 errors**

- [ ] **Step 5: Migrate `components/DisclaimerModal.tsx`** — maxWidth="xl", no onClose

- [ ] **Step 6: Migrate `components/MaintenanceNoticeModal.tsx`** — maxWidth="lg", no onClose

- [ ] **Step 7: Migrate `components/RegisterRequestModal.tsx`** — maxWidth="md", no onClose

- [ ] **Step 8: Run lsp_diagnostics (severity: error) on remaining 3 files — expect 0 errors each**

- [ ] **Step 9: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  components/ChangePasswordModal.tsx \
  components/SetEmailModal.tsx \
  components/DisclaimerModal.tsx \
  components/MaintenanceNoticeModal.tsx \
  components/RegisterRequestModal.tsx; do
  count=$(grep -c "fixed inset-0" "$BASE/$f")
  echo "$f: $count (expect 0)"
done
```

- [ ] **Step 10: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/ChangePasswordModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/SetEmailModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/DisclaimerModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/MaintenanceNoticeModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/RegisterRequestModal.tsx
git commit -m "refactor: migrate root modal components to ModalShell"
```

---

## Task 3: Migrate ModalShell — Settings Components (8 files)

**Files to modify:**
- `components/settings/ConfirmDialog.tsx` (maxWidth="sm", onClose=no)
- `components/settings/CreateUserModal.tsx` (maxWidth="md", onClose=yes)
- `components/settings/EditUserModal.tsx` (maxWidth="md", onClose=yes)
- `components/settings/EmailTemplateModal.tsx` (maxWidth="lg", onClose=yes)
- `components/settings/PermissionModal.tsx` (maxWidth="md", onClose=yes)
- `components/settings/DatasetPermissionModal.tsx` (maxWidth="lg", onClose=yes)
- `components/settings/MigrationModal.tsx` (maxWidth="md", onClose=no)
- `components/settings/PermissionCenterModal.tsx` (maxWidth="6xl", onClose=yes)

**Import path for settings/ files:** `import { ModalShell } from '../ui/modal-shell'`

**Special case — `ConfirmDialog.tsx`:** This component checks `dialog.isOpen` internally (not a prop called `isOpen`). Use `<ModalShell isOpen={dialog.isOpen} maxWidth="sm">`. The current `if (!dialog.isOpen) return null` guard is replaced by ModalShell's own guard.

**Special case — `PermissionCenterModal.tsx`:** This is a large file. This component is always mounted conditionally by its parent, so it renders when it's open. Find the `fixed inset-0` overlay div and its matching white container div, replace both with `<ModalShell isOpen={true} onClose={onClose} maxWidth="6xl">`. The `onClose` prop already exists on this component.

- [ ] **Step 1: Migrate all 8 settings modal files** (one at a time — read → identify backdrop+container div pair → replace with ModalShell → verify diagnostics after each)

  For each file: add `import { ModalShell } from '../ui/modal-shell'`, replace the two-div structure, keep children, verify lsp_diagnostics (severity: error) → 0 errors.

- [ ] **Step 2: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  components/settings/ConfirmDialog.tsx \
  components/settings/CreateUserModal.tsx \
  components/settings/EditUserModal.tsx \
  components/settings/EmailTemplateModal.tsx \
  components/settings/PermissionModal.tsx \
  components/settings/DatasetPermissionModal.tsx \
  components/settings/MigrationModal.tsx \
  components/settings/PermissionCenterModal.tsx; do
  count=$(grep -c "fixed inset-0" "$BASE/$f")
  echo "$f: $count (expect 0)"
done
```

- [ ] **Step 3: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/settings/ConfirmDialog.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/CreateUserModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/EditUserModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/EmailTemplateModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/DatasetPermissionModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/MigrationModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionCenterModal.tsx
git commit -m "refactor: migrate settings modal components to ModalShell"
```

---

## Task 4: Migrate ModalShell — List + Training Components (8 files)

**Files to modify (8 files, containing 10 modal components total):**
- `components/list/ExportLabelsModal.tsx` (maxWidth="md", onClose=yes)
- `components/list/FileMetadataModal.tsx` (maxWidth="lg", onClose=yes)
- `components/list/DeleteModals.tsx` — contains 2 separate modal components: `DeleteConfirmModal` (maxWidth="lg", onClose=no) and `BatchDeleteModal` (maxWidth="lg", onClose=no)
- `components/list/EditModals.tsx` — contains 3 separate modal components: `EditMetadataModal` (maxWidth="md", onClose=yes via cancel), `BatchEditModal` (maxWidth="md", onClose=yes), `EditDatasetModal` (maxWidth="md", onClose=yes)
- `components/training/DeleteConfirmModal.tsx` (maxWidth="md", onClose=no)
- `components/training/EditMetadataModal.tsx` (maxWidth="md", onClose=yes)
- `components/training/BatchEditModal.tsx` (maxWidth="md", onClose=yes)
- `components/training/FileMetadataModal.tsx` (maxWidth="lg", onClose=yes)

**Import path for list/ and training/ files:** `import { ModalShell } from '../ui/modal-shell'`

**Special case — `EditModals.tsx` `EditDatasetModal`:** The current outer div has `onClick={onCancel}` for backdrop close. Replace it with `<ModalShell isOpen={true} onClose={onCancel} maxWidth="md">`. The inner `onClick={e => e.stopPropagation()}` is also removed (ModalShell handles this internally). The component is always conditionally mounted by its parent.

**Special case — multi-component files:** `DeleteModals.tsx` and `EditModals.tsx` each contain multiple named export functions. Each function has its own overlay div — replace each one independently. A single `import { ModalShell }` at the top of the file covers all components in that file.

- [ ] **Step 1: Migrate `components/list/ExportLabelsModal.tsx`** — read, replace overlay+container, verify lsp_diagnostics

- [ ] **Step 2: Migrate `components/list/FileMetadataModal.tsx`**

- [ ] **Step 3: Migrate `components/list/DeleteModals.tsx`** — replace both DeleteConfirmModal and BatchDeleteModal overlay divs

- [ ] **Step 4: Migrate `components/list/EditModals.tsx`** — replace all 3 modal component overlay divs

- [ ] **Step 5: Migrate `components/training/DeleteConfirmModal.tsx`**

- [ ] **Step 6: Migrate `components/training/EditMetadataModal.tsx`**

- [ ] **Step 7: Migrate `components/training/BatchEditModal.tsx`**

- [ ] **Step 8: Migrate `components/training/FileMetadataModal.tsx`**

- [ ] **Step 9: Run lsp_diagnostics (severity: error) on all 8 files — expect 0 errors each**

- [ ] **Step 10: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  components/list/ExportLabelsModal.tsx \
  components/list/FileMetadataModal.tsx \
  components/list/DeleteModals.tsx \
  components/list/EditModals.tsx \
  components/training/DeleteConfirmModal.tsx \
  components/training/EditMetadataModal.tsx \
  components/training/BatchEditModal.tsx \
  components/training/FileMetadataModal.tsx; do
  count=$(grep -c "fixed inset-0" "$BASE/$f")
  echo "$f: $count (expect 0)"
done
```

- [ ] **Step 11: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/list/ExportLabelsModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/list/FileMetadataModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/list/DeleteModals.tsx \
  pathlab/pathlab-client/src/renderer/src/components/list/EditModals.tsx \
  pathlab/pathlab-client/src/renderer/src/components/training/DeleteConfirmModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/training/EditMetadataModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/training/BatchEditModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/training/FileMetadataModal.tsx
git commit -m "refactor: migrate list and training modal components to ModalShell"
```

---

## Task 5: Roll Out useDebounce (2 files)

**Files to modify:**
- `components/settings/PermissionCenterModal.tsx`
- `components/upload/DatasetConfigStep.tsx`

### PermissionCenterModal.tsx

- [ ] **Step 1: Read the file and locate the 3 debounce state+effect blocks**

They look like this (search for `setDebouncedUserSearchQuery`, `setDebouncedDatasetSearchQuery`, `setDebouncedGrantUserSearchQuery`):
```typescript
const [debouncedUserSearchQuery, setDebouncedUserSearchQuery] = useState("")
useEffect(() => {
  const timer = window.setTimeout(() => setDebouncedUserSearchQuery(userSearchQuery), SEARCH_DEBOUNCE_MS)
  return () => window.clearTimeout(timer)
}, [userSearchQuery])
```
(× 3 for the 3 different search queries)

- [ ] **Step 2: Add import and replace all 3 blocks**

Add at top: `import { useDebounce } from '../../lib/useDebounce'`

Replace each `useState` + `useEffect` block with a single line:
```typescript
const debouncedUserSearchQuery = useDebounce(userSearchQuery, SEARCH_DEBOUNCE_MS)
const debouncedDatasetSearchQuery = useDebounce(datasetSearchQuery, SEARCH_DEBOUNCE_MS)
const debouncedGrantUserSearchQuery = useDebounce(grantUserSearchQuery, SEARCH_DEBOUNCE_MS)
```

Delete: the 3 `useState` declarations (for the debounced variables) and the 3 `useEffect` blocks.

- [ ] **Step 3: Run lsp_diagnostics (severity: error) — expect 0 errors**

- [ ] **Step 4: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
# Debounced setter calls must be gone:
grep -c "setDebouncedUserSearchQuery\|setDebouncedDatasetSearchQuery\|setDebouncedGrantUserSearchQuery" \
  "$BASE/components/settings/PermissionCenterModal.tsx"
# Expected: 0

# Import must exist:
grep -c "import.*useDebounce" "$BASE/components/settings/PermissionCenterModal.tsx"
# Expected: 1
```

### DatasetConfigStep.tsx

- [ ] **Step 5: Read the file, locate the 2 debounce blocks (window.setTimeout + clearTimeout), apply same replacement pattern**

Add: `import { useDebounce } from '../../lib/useDebounce'`  
Remove: the 2 `useState + useEffect + setTimeout/clearTimeout` blocks  
Add: 2 `useDebounce` calls

- [ ] **Step 6: Run lsp_diagnostics (severity: error) — expect 0 errors**

- [ ] **Step 7: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
grep -c "setTimeout\|clearTimeout" "$BASE/components/upload/DatasetConfigStep.tsx"
# Expected: 0

grep -c "import.*useDebounce" "$BASE/components/upload/DatasetConfigStep.tsx"
# Expected: 1
```

- [ ] **Step 8: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionCenterModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/upload/DatasetConfigStep.tsx
git commit -m "refactor: replace inline debounce useEffects with useDebounce hook"
```

---

## Task 6: Roll Out useConfirmDialog — Pages (4 files)

**Files to modify:**
- `pages/ListPage.tsx`
- `pages/TaskListPage.tsx`
- `pages/TaskDetailPage.tsx`
- `pages/NewTaskPage.tsx`

**Import:** `import { useConfirmDialog } from '../lib/useConfirmDialog'`

**Migration pattern:**

1. Find the local `useState<ConfirmDialogState>(...)` declaration — delete it
2. Find the local `showConfirmDialog` and `closeConfirmDialog` function definitions — delete them
3. Add: `const { dialogState, showConfirmDialog, closeConfirmDialog } = useConfirmDialog()`
4. The JSX `<ConfirmDialog dialog={...} onClose={...} />` is already rendered — verify it uses `dialogState` and `closeConfirmDialog` (update variable references if different names were used)

- [ ] **Step 1: Migrate `pages/ListPage.tsx`**

- [ ] **Step 2: Run lsp_diagnostics (severity: error) on ListPage.tsx — expect 0 errors**

- [ ] **Step 3: Migrate `pages/TaskListPage.tsx`**

- [ ] **Step 4: Migrate `pages/TaskDetailPage.tsx`**

- [ ] **Step 5: Migrate `pages/NewTaskPage.tsx`**

- [ ] **Step 6: Run lsp_diagnostics (severity: error) on all 4 files — expect 0 errors**

- [ ] **Step 7: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in pages/ListPage.tsx pages/TaskListPage.tsx pages/TaskDetailPage.tsx pages/NewTaskPage.tsx; do
  echo "=== $f ==="
  echo "useState<ConfirmDialogState> (expect 0): $(grep -c 'useState<ConfirmDialogState>' $BASE/$f)"
  echo "import useConfirmDialog (expect 1): $(grep -c 'import.*useConfirmDialog' $BASE/$f)"
done
```

- [ ] **Step 8: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/pages/ListPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/TaskListPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/TaskDetailPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/NewTaskPage.tsx
git commit -m "refactor: migrate pages to useConfirmDialog hook"
```

---

## Task 7: Roll Out useConfirmDialog — Settings Components (8 files)

**Files to modify:**
- `components/settings/UsersTab.tsx` — **also the parent of `PermissionCenterModal`; add hook here and pass props down**
- `components/settings/StorageTab.tsx`
- `components/settings/ModelsTab.tsx`
- `components/settings/AnnotationAuditCard.tsx`
- `components/settings/DatasetPermissionModal.tsx`
- `components/settings/PermissionModal.tsx`

**Note on `PermissionCenterModal`:** This modal receives `showConfirmDialog` and `closeConfirmDialog` as props from its parent, `UsersTab.tsx`. Do NOT change `PermissionCenterModal`'s prop interface. Instead, in `UsersTab.tsx`:
1. Import and call `useConfirmDialog()`
2. Pass the returned `showConfirmDialog` and `closeConfirmDialog` to `<PermissionCenterModal>` as props (replacing whatever local state was there before)
3. Render `<ConfirmDialog dialog={dialogState} onClose={closeConfirmDialog} />` at the end of `UsersTab`'s JSX

**Import path for settings/:** `import { useConfirmDialog } from '../../lib/useConfirmDialog'`

**Migration pattern:** Same as Task 6.

- [ ] **Step 1: Migrate `components/settings/UsersTab.tsx`** (includes PermissionCenterModal parent wiring)

- [ ] **Step 2: Run lsp_diagnostics (severity: error) on UsersTab.tsx — expect 0 errors**

- [ ] **Step 3: Migrate `components/settings/StorageTab.tsx`**

- [ ] **Step 4: Migrate `components/settings/ModelsTab.tsx`**

- [ ] **Step 5: Migrate `components/settings/AnnotationAuditCard.tsx`**

- [ ] **Step 6: Migrate `components/settings/DatasetPermissionModal.tsx`**

- [ ] **Step 7: Migrate `components/settings/PermissionModal.tsx`**

- [ ] **Step 8: Run lsp_diagnostics (severity: error) on all 6 remaining files — expect 0 errors**

- [ ] **Step 9: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  components/settings/UsersTab.tsx \
  components/settings/StorageTab.tsx \
  components/settings/ModelsTab.tsx \
  components/settings/AnnotationAuditCard.tsx \
  components/settings/DatasetPermissionModal.tsx \
  components/settings/PermissionModal.tsx; do
  echo "=== $f ==="
  echo "useState<ConfirmDialogState> (expect 0): $(grep -c 'useState<ConfirmDialogState>' $BASE/$f)"
  echo "import useConfirmDialog (expect 1): $(grep -c 'import.*useConfirmDialog' $BASE/$f)"
done
```

- [ ] **Step 10: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/settings/UsersTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/StorageTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/ModelsTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/AnnotationAuditCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/DatasetPermissionModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionModal.tsx
git commit -m "refactor: migrate settings components to useConfirmDialog hook"
```

---

## Task 8: Roll Out useAsyncAction — Pages (6 files)

**Files to modify:**
- `pages/StorageManagementPage.tsx` — handlers: `detectOrphaned`, `handleCleanup`, empty dataset cleanup handler
- `pages/TaskDetailPage.tsx` — handlers: `handleRerun`, `handleCancel`
- `pages/TaskListPage.tsx` — handler: `handleDeleteTask`
- `pages/ResultsViewerPage.tsx` — handlers: `runAnalysis`, `startExternalValidation`
- `pages/NewTaskPage.tsx` — async handlers: `handleSubmitTask` and any others with `setX(true)/try/finally/setX(false)`
- `pages/AIChatPage.tsx` — async handlers

**Import:** `import { useAsyncAction } from '../lib/useAsyncAction'`

**Scope reminder:** ONLY migrate handlers with this pattern:
```typescript
setLoading(true)   // or setIsPending(true) / setIsLoading(true) / setSubmitting(true)
try { await apiCall() }
catch (err) { setError(...) }
finally { setLoading(false) }
```
Do NOT touch `useQuery` fetches, `useEffect` data loads, or polling intervals.

**Migration pattern:**
```typescript
// BEFORE
const [loading, setLoading] = useState(false)
const [error, setError] = useState<string | null>(null)
const handler = async () => {
  setLoading(true)
  setError(null)
  try { const data = await apiCall(); setData(data) }
  catch (err) { setError(err instanceof Error ? err.message : t('error')) }
  finally { setLoading(false) }
}

// AFTER
import { useAsyncAction } from '../lib/useAsyncAction'
const [error, setError] = useState<string | null>(null)
const [loading, runHandler] = useAsyncAction({
  onError: (err) => setError(err instanceof Error ? err.message : t('error'))
})
const handler = () => {
  setError(null)
  return runHandler(async () => {
    const data = await apiCall()
    setData(data)
  })
}
```

If the file uses `useToast()` for errors instead of local error state, use `onError: (err) => toastError(...)`.

- [ ] **Step 1: Migrate `pages/StorageManagementPage.tsx`** — read, identify all `setLoadingX(true)` blocks in handlers, apply migration

- [ ] **Step 2: Run lsp_diagnostics (severity: error) — expect 0 errors**

- [ ] **Step 3: Migrate `pages/TaskDetailPage.tsx`**

- [ ] **Step 4: Migrate `pages/TaskListPage.tsx`**

- [ ] **Step 5: Migrate `pages/ResultsViewerPage.tsx`**

- [ ] **Step 6: Migrate `pages/NewTaskPage.tsx`**

- [ ] **Step 7: Migrate `pages/AIChatPage.tsx`**

- [ ] **Step 8: Run lsp_diagnostics (severity: error) on all 6 files — expect 0 errors**

- [ ] **Step 9: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  pages/StorageManagementPage.tsx pages/TaskDetailPage.tsx pages/TaskListPage.tsx \
  pages/ResultsViewerPage.tsx pages/NewTaskPage.tsx pages/AIChatPage.tsx; do
  echo "=== $f ==="
  echo "setLoading(true) (expect 0): $(grep -cF 'setLoading(true)' $BASE/$f)"
  echo "setIsLoading(true) (expect 0): $(grep -cF 'setIsLoading(true)' $BASE/$f)"
  echo "setSubmitting(true) (expect 0): $(grep -cF 'setSubmitting(true)' $BASE/$f)"
  echo "import useAsyncAction (expect 1): $(grep -c 'import.*useAsyncAction' $BASE/$f)"
done
```

- [ ] **Step 10: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/pages/StorageManagementPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/TaskDetailPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/TaskListPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/ResultsViewerPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/NewTaskPage.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/AIChatPage.tsx
git commit -m "refactor: migrate page handlers to useAsyncAction"
```

---

## Task 9: Roll Out useAsyncAction — Settings Components (8 files)

**Files to modify:**
- `components/settings/UsersTab.tsx`
- `components/settings/ModelsTab.tsx`
- `components/settings/FeedbackTab.tsx`
- `components/settings/TasksTab.tsx`
- `components/settings/GeneralTab.tsx`
- `components/settings/StorageTab.tsx`
- `components/settings/AnnotationAuditCard.tsx`
- `components/settings/PermissionCenterModal.tsx`

**Import path:** `import { useAsyncAction } from '../../lib/useAsyncAction'`

**Pattern:** Same as Task 8 — read each file, identify handlers with `setX(true)/try/catch/finally/setX(false)`, migrate.

- [ ] **Step 1: Migrate all 8 settings files** (one at a time — read → identify targets → migrate → verify lsp_diagnostics)

- [ ] **Step 2: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  components/settings/UsersTab.tsx components/settings/ModelsTab.tsx \
  components/settings/FeedbackTab.tsx components/settings/TasksTab.tsx \
  components/settings/GeneralTab.tsx components/settings/StorageTab.tsx \
  components/settings/AnnotationAuditCard.tsx components/settings/PermissionCenterModal.tsx; do
  echo "=== $f ==="
  echo "setLoading(true) (expect 0): $(grep -cF 'setLoading(true)' $BASE/$f)"
  echo "setIsLoading(true) (expect 0): $(grep -cF 'setIsLoading(true)' $BASE/$f)"
  echo "setSubmitting(true) (expect 0): $(grep -cF 'setSubmitting(true)' $BASE/$f)"
  echo "import useAsyncAction (expect 1): $(grep -c 'import.*useAsyncAction' $BASE/$f)"
done
```

- [ ] **Step 3: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/settings/UsersTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/ModelsTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/FeedbackTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/TasksTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/GeneralTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/StorageTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/AnnotationAuditCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionCenterModal.tsx
git commit -m "refactor: migrate settings component handlers to useAsyncAction"
```

---

## Task 10: Roll Out useAsyncAction — Other Components (12 files)

**Files to modify:**
- `components/WSIViewer.tsx`
- `components/wsiViewer/ShareAnnotationDialog.tsx`
- `components/chat/AnalysisConfigCard.tsx`
- `components/chat/TaskConfigCard.tsx`
- `components/chat/DatasetRegistrationCard.tsx`
- `components/chat/TaskHistoryCard.tsx`
- `components/chat/ChartCard.tsx`
- `components/chat/MetricCard.tsx`
- `components/chat/ImageRecommendationCard.tsx`
- `components/chat/QuickAnalysisViewer.tsx`
- `components/settings/DatasetPermissionModal.tsx`
- `components/settings/PermissionModal.tsx`

**Import paths:**
- `components/WSIViewer.tsx`: `import { useAsyncAction } from '../lib/useAsyncAction'`
- `components/wsiViewer/`, `components/chat/`, `components/settings/`: `import { useAsyncAction } from '../../lib/useAsyncAction'`

**Pattern:** Same as Tasks 8–9.

- [ ] **Step 1: Migrate all 12 files** (read each → identify `setX(true)/try/catch/finally` patterns in handlers → migrate → verify lsp_diagnostics)

- [ ] **Step 2: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  components/WSIViewer.tsx \
  components/wsiViewer/ShareAnnotationDialog.tsx \
  components/chat/AnalysisConfigCard.tsx \
  components/chat/TaskConfigCard.tsx \
  components/chat/DatasetRegistrationCard.tsx \
  components/chat/TaskHistoryCard.tsx \
  components/chat/ChartCard.tsx \
  components/chat/MetricCard.tsx \
  components/chat/ImageRecommendationCard.tsx \
  components/chat/QuickAnalysisViewer.tsx \
  components/settings/DatasetPermissionModal.tsx \
  components/settings/PermissionModal.tsx; do
  echo "=== $f ==="
  echo "setLoading(true) (expect 0): $(grep -cF 'setLoading(true)' $BASE/$f)"
  echo "setIsLoading(true) (expect 0): $(grep -cF 'setIsLoading(true)' $BASE/$f)"
  echo "setSubmitting(true) (expect 0): $(grep -cF 'setSubmitting(true)' $BASE/$f)"
  echo "import useAsyncAction (expect 1): $(grep -c 'import.*useAsyncAction' $BASE/$f)"
done
```

- [ ] **Step 3: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/WSIViewer.tsx \
  pathlab/pathlab-client/src/renderer/src/components/wsiViewer/ShareAnnotationDialog.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/AnalysisConfigCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/TaskConfigCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/DatasetRegistrationCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/TaskHistoryCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/ChartCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/MetricCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/ImageRecommendationCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/chat/QuickAnalysisViewer.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/DatasetPermissionModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionModal.tsx
git commit -m "refactor: migrate component handlers to useAsyncAction"
```

---

## Task 11: Roll Out PaginationFooter (6 files)

**Files to modify:**
- `components/settings/PermissionCenterModal.tsx` — delete internal `PaginationFooter` subcomponent, import public one
- `components/settings/UsersTab.tsx` — replace own pagination JSX
- `components/settings/ModelsTab.tsx` — replace own pagination JSX
- `components/settings/FeedbackTab.tsx` — replace own pagination JSX
- `components/settings/AnnotationAuditCard.tsx` — replace own pagination JSX
- `pages/ListPage.tsx` — replace own pagination JSX

**Import paths:**
- `components/settings/*.tsx`: `import { PaginationFooter } from '../ui/pagination-footer'`
- `pages/ListPage.tsx`: `import { PaginationFooter } from '../components/ui/pagination-footer'`

**PermissionCenterModal special step:** Search for `function PaginationFooter` inside the file (around line 77). Delete the entire local function definition (lines ~77–143). Then add the import at the top.

**Migration pattern for other files:**

1. Find the existing pagination div/markup (typically contains prev/next buttons and page-size selector)
2. Replace with:
```tsx
<PaginationFooter
  page={page}
  pageSize={pageSize}
  total={total}
  disabled={loading}
  onPageChange={setPage}
  onPageSizeChange={(size) => { setPageSize(size); setPage(1) }}
/>
```
3. Adjust prop names to match the file's actual state variable names

- [ ] **Step 1: Migrate `components/settings/PermissionCenterModal.tsx`** — delete local PaginationFooter function, add import, update all 2 call sites to remove the `t={t}` prop

- [ ] **Step 2: Run lsp_diagnostics (severity: error) — expect 0 errors**

- [ ] **Step 3: Migrate `components/settings/UsersTab.tsx`**

- [ ] **Step 4: Migrate `components/settings/ModelsTab.tsx`**

- [ ] **Step 5: Migrate `components/settings/FeedbackTab.tsx`**

- [ ] **Step 6: Migrate `components/settings/AnnotationAuditCard.tsx`**

- [ ] **Step 7: Migrate `pages/ListPage.tsx`**

- [ ] **Step 8: Run lsp_diagnostics (severity: error) on all 6 files — expect 0 errors each**

- [ ] **Step 9: Verify success criteria**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
for f in \
  components/settings/PermissionCenterModal.tsx \
  components/settings/UsersTab.tsx \
  components/settings/ModelsTab.tsx \
  components/settings/FeedbackTab.tsx \
  components/settings/AnnotationAuditCard.tsx \
  pages/ListPage.tsx; do
  echo "=== $f ==="
  echo "import PaginationFooter (expect 1): $(grep -c 'import.*PaginationFooter' $BASE/$f)"
done
```

- [ ] **Step 10: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionCenterModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/UsersTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/ModelsTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/FeedbackTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/AnnotationAuditCard.tsx \
  pathlab/pathlab-client/src/renderer/src/pages/ListPage.tsx
git commit -m "refactor: replace inline pagination with shared PaginationFooter component"
```

---

## Task 12: Final Verification

- [ ] **Step 1: Run full success criteria sweep**

```bash
BASE=pathlab/pathlab-client/src/renderer/src
echo "======= ModalShell: fixed inset-0 must be 0 in all 21 modal files ======="
for f in \
  components/ChangePasswordModal.tsx components/SetEmailModal.tsx \
  components/DisclaimerModal.tsx components/MaintenanceNoticeModal.tsx \
  components/RegisterRequestModal.tsx \
  components/settings/ConfirmDialog.tsx components/settings/CreateUserModal.tsx \
  components/settings/EditUserModal.tsx components/settings/EmailTemplateModal.tsx \
  components/settings/PermissionModal.tsx components/settings/DatasetPermissionModal.tsx \
  components/settings/MigrationModal.tsx components/settings/PermissionCenterModal.tsx \
  components/list/ExportLabelsModal.tsx components/list/FileMetadataModal.tsx \
  components/list/DeleteModals.tsx components/list/EditModals.tsx \
  components/training/DeleteConfirmModal.tsx components/training/EditMetadataModal.tsx \
  components/training/BatchEditModal.tsx components/training/FileMetadataModal.tsx; do
  count=$(grep -c "fixed inset-0" "$BASE/$f" 2>/dev/null && true || echo 0)
  echo "$f: $count (expect 0)"
done

echo "======= useDebounce ======="
echo "setDebouncedX in PermissionCenterModal (expect 0): $(grep -cF 'setDebouncedUserSearchQuery' $BASE/components/settings/PermissionCenterModal.tsx)"
echo "setTimeout in DatasetConfigStep (expect 0): $(grep -cF 'setTimeout' $BASE/components/upload/DatasetConfigStep.tsx)"

echo "======= useConfirmDialog (expect 0 useState<ConfirmDialogState>, 1 import) ======="
for f in \
  pages/ListPage.tsx pages/TaskListPage.tsx pages/TaskDetailPage.tsx pages/NewTaskPage.tsx \
  components/settings/UsersTab.tsx components/settings/StorageTab.tsx \
  components/settings/ModelsTab.tsx components/settings/AnnotationAuditCard.tsx \
  components/settings/DatasetPermissionModal.tsx components/settings/PermissionModal.tsx; do
  s=$(grep -cF 'useState<ConfirmDialogState>' "$BASE/$f" 2>/dev/null || echo 0)
  i=$(grep -c 'import.*useConfirmDialog' "$BASE/$f" 2>/dev/null || echo 0)
  echo "$f: useState=$s(expect 0) import=$i(expect 1)"
done

echo "======= useAsyncAction (expect 0 setLoading(true), 1 import) ======="
for f in \
  pages/StorageManagementPage.tsx pages/TaskDetailPage.tsx pages/TaskListPage.tsx \
  pages/ResultsViewerPage.tsx pages/NewTaskPage.tsx pages/AIChatPage.tsx \
  components/settings/UsersTab.tsx components/settings/ModelsTab.tsx \
  components/settings/FeedbackTab.tsx components/settings/TasksTab.tsx \
  components/settings/GeneralTab.tsx components/settings/StorageTab.tsx \
  components/settings/AnnotationAuditCard.tsx components/settings/PermissionCenterModal.tsx \
  components/WSIViewer.tsx components/wsiViewer/ShareAnnotationDialog.tsx \
  components/chat/AnalysisConfigCard.tsx components/chat/TaskConfigCard.tsx \
  components/chat/DatasetRegistrationCard.tsx components/chat/TaskHistoryCard.tsx \
  components/chat/ChartCard.tsx components/chat/MetricCard.tsx \
  components/chat/ImageRecommendationCard.tsx components/chat/QuickAnalysisViewer.tsx \
  components/settings/DatasetPermissionModal.tsx components/settings/PermissionModal.tsx; do
  s=$(grep -cF 'setLoading(true)' "$BASE/$f" 2>/dev/null || echo 0)
  i=$(grep -c 'import.*useAsyncAction' "$BASE/$f" 2>/dev/null || echo 0)
  echo "$f: setLoading=$s(expect 0) import=$i(expect 1)"
done

echo "======= No as any / ts-ignore / ts-expect-error introduced ======="
git diff main..HEAD -- "$BASE" | grep '^\+' | grep -c 'as any\|@ts-ignore\|@ts-expect-error' || echo 0
# Expected: 0
```

- [ ] **Step 2: Run lsp_diagnostics on full renderer/src directory** (`severity: "error"`, note any pre-existing errors from unrelated files as expected — do NOT fix them)

- [ ] **Step 3: Final commit**

```bash
git add -A
git status  # review — should be clean (nothing to add)
# If clean, no commit needed; if any files are unstaged, investigate
```

