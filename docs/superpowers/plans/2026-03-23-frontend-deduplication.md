# Frontend Deduplication Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate ~1,400 lines of redundant frontend code by extracting 4 shared primitives and migrating 47 files to use them — zero behaviour change.

**Architecture:** Four new primitives (ModalShell, useDebounce, useConfirmDialog, PaginationFooter) are created first as pure additions, then consumed by existing files via targeted migration. All changes are verifiable with `lsp_diagnostics` + grep success criteria from the spec.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, react-i18next, Electron (renderer process)

**Spec:** `docs/superpowers/specs/2026-03-23-frontend-deduplication-design.md`

**Base path:** `pathlab/pathlab-client/src/renderer/src/`

---

## File Map

**New files (create):**
- `lib/useDebounce.ts`
- `lib/useConfirmDialog.ts`
- `components/ui/modal-shell.tsx`
- `components/ui/pagination-footer.tsx`

**Modified files (migrate):**
- 22 modal files → ModalShell (Tasks 2–4)
- 2 files → useDebounce (Task 5)
- 11 files → useConfirmDialog (Tasks 6–7)
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
import { useEffect } from 'react'
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

Copy the exact `PaginationFooter` implementation out of `components/settings/PermissionCenterModal.tsx` (lines ~77–143), remove the `t` prop, and call `useTranslation()` internally:

```typescript
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

- [ ] **Step 5: Run lsp_diagnostics on all 4 new files, verify clean**

Check: `lib/useDebounce.ts`, `lib/useConfirmDialog.ts`, `components/ui/modal-shell.tsx`, `components/ui/pagination-footer.tsx` — all must have 0 errors.

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
   (adjust relative path for files in subdirectories)
2. Find the outermost `<div className="fixed inset-0 ...">` and its matching closing `</div>`
3. Replace that outer div pair with:
   - If `onClose=yes`: `<ModalShell isOpen={isOpen} onClose={onClose} maxWidth="???">`…`</ModalShell>`
   - If `onClose=no`: `<ModalShell isOpen={isOpen} maxWidth="???">`…`</ModalShell>`
4. The inner content div (white box) is also replaced by ModalShell's container — **delete it too** (ModalShell renders the white box itself)
5. The remaining children are just the header/body/footer content of the modal

**Important:** Both the backdrop div AND the white content box div are replaced. Only the internal content (title, form, buttons) is kept as `children`.

- [ ] **Step 1: Migrate `components/ChangePasswordModal.tsx`**

Read the file. Find the `fixed inset-0` overlay div and the `bg-white rounded-...` content div. Replace both with `<ModalShell isOpen={isOpen} onClose={onClose} maxWidth="md">`. Keep everything inside.

- [ ] **Step 2: Verify `lsp_diagnostics` clean on ChangePasswordModal.tsx**

- [ ] **Step 3: Migrate `components/SetEmailModal.tsx`** — same approach, `maxWidth="md"`, `onClose={onClose}`

- [ ] **Step 4: Verify lsp_diagnostics clean**

- [ ] **Step 5: Migrate `components/DisclaimerModal.tsx`** — `maxWidth="xl"`, no `onClose` prop (modal has no backdrop dismiss)

- [ ] **Step 6: Migrate `components/MaintenanceNoticeModal.tsx`** — `maxWidth="lg"`, no `onClose`

- [ ] **Step 7: Migrate `components/RegisterRequestModal.tsx`** — `maxWidth="md"`, no `onClose`

- [ ] **Step 8: Verify lsp_diagnostics clean on all 5 files**

- [ ] **Step 9: Verify success criteria**

```bash
# Each of these must print 0 lines:
grep "fixed inset-0" pathlab/pathlab-client/src/renderer/src/components/ChangePasswordModal.tsx
grep "fixed inset-0" pathlab/pathlab-client/src/renderer/src/components/SetEmailModal.tsx
grep "fixed inset-0" pathlab/pathlab-client/src/renderer/src/components/DisclaimerModal.tsx
grep "fixed inset-0" pathlab/pathlab-client/src/renderer/src/components/MaintenanceNoticeModal.tsx
grep "fixed inset-0" pathlab/pathlab-client/src/renderer/src/components/RegisterRequestModal.tsx
```

- [ ] **Step 10: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/components/ChangePasswordModal.tsx \
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

**Import path for settings/:** `import { ModalShell } from '../ui/modal-shell'`

**Special case — `ConfirmDialog.tsx`:** This component receives `dialog.isOpen` as the open flag (not a standalone `isOpen` prop). Use `<ModalShell isOpen={dialog.isOpen} maxWidth="sm">`.

**Special case — `PermissionCenterModal.tsx`:** This is a large file (~1800 lines). Find the outermost `<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">` and the inner `<div className="relative max-h-[90vh] w-full max-w-6xl ...">`. Replace both with `<ModalShell isOpen={true} onClose={onClose} maxWidth="6xl">`. Note: this modal is always mounted conditionally by its parent, so `isOpen={true}` is correct.

- [ ] **Step 1: Migrate all 8 settings modal files** (one at a time, using the pattern described above)

  For each file:
  1. Add `import { ModalShell } from '../ui/modal-shell'`
  2. Replace the `fixed inset-0` overlay + `bg-white rounded...` container with `<ModalShell ...>`
  3. Keep inner content as children

- [ ] **Step 2: Verify lsp_diagnostics clean on all 8 files**

- [ ] **Step 3: Verify success criteria**

```bash
for f in ConfirmDialog CreateUserModal EditUserModal EmailTemplateModal PermissionModal DatasetPermissionModal MigrationModal PermissionCenterModal; do
  grep "fixed inset-0" "pathlab/pathlab-client/src/renderer/src/components/settings/${f}.tsx"
done
# All must produce 0 output
```

- [ ] **Step 4: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/components/settings/ConfirmDialog.tsx \
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

## Task 4: Migrate ModalShell — List + Training Components (9 files)

**Files to modify:**
- `components/list/ExportLabelsModal.tsx` (maxWidth="md", onClose=yes)
- `components/list/FileMetadataModal.tsx` (maxWidth="lg", onClose=yes)
- `components/list/DeleteModals.tsx` — contains 2 modal components: `DeleteConfirmModal` (maxWidth="lg", onClose=no) and `BatchDeleteModal` (maxWidth="lg", onClose=no)
- `components/list/EditModals.tsx` — contains 3 modal components: `EditMetadataModal` (maxWidth="md", onClose=yes via cancel), `BatchEditModal` (maxWidth="md", onClose=yes), `EditDatasetModal` (maxWidth="md", onClose=yes)
- `components/training/DeleteConfirmModal.tsx` (maxWidth="md", onClose=no)
- `components/training/EditMetadataModal.tsx` (maxWidth="md", onClose=yes)
- `components/training/BatchEditModal.tsx` (maxWidth="md", onClose=yes)
- `components/training/FileMetadataModal.tsx` (maxWidth="lg", onClose=yes)

**Import path for list/ and training/:** `import { ModalShell } from '../ui/modal-shell'`

**Special case — `EditModals.tsx` and `DeleteModals.tsx`:** Each file contains multiple modal components. Each component has its own overlay div — replace each one independently.

**Special case — `EditModals.tsx` `EditDatasetModal`:** This modal uses `onClick={onCancel}` on the outer div for backdrop close. With ModalShell, replace the outer div with `<ModalShell isOpen={true} onClose={onCancel} maxWidth="md">` and remove the outer `onClick`. The inner `onClick={e => e.stopPropagation()}` is also removed (ModalShell handles this internally).

- [ ] **Step 1: Migrate `components/list/ExportLabelsModal.tsx`**

- [ ] **Step 2: Migrate `components/list/FileMetadataModal.tsx`**

- [ ] **Step 3: Migrate `components/list/DeleteModals.tsx`** (both DeleteConfirmModal and BatchDeleteModal)

- [ ] **Step 4: Migrate `components/list/EditModals.tsx`** (all 3 modal components in the file)

- [ ] **Step 5: Migrate `components/training/DeleteConfirmModal.tsx`**

- [ ] **Step 6: Migrate `components/training/EditMetadataModal.tsx`**

- [ ] **Step 7: Migrate `components/training/BatchEditModal.tsx`**

- [ ] **Step 8: Migrate `components/training/FileMetadataModal.tsx`**

- [ ] **Step 9: Verify lsp_diagnostics clean on all 9 files**

- [ ] **Step 10: Verify success criteria**

```bash
for f in \
  "components/list/ExportLabelsModal.tsx" \
  "components/list/FileMetadataModal.tsx" \
  "components/list/DeleteModals.tsx" \
  "components/list/EditModals.tsx" \
  "components/training/DeleteConfirmModal.tsx" \
  "components/training/EditMetadataModal.tsx" \
  "components/training/BatchEditModal.tsx" \
  "components/training/FileMetadataModal.tsx"; do
  grep "fixed inset-0" "pathlab/pathlab-client/src/renderer/src/${f}"
done
# All must produce 0 output
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

The 3 targets (around lines 220–417):
```typescript
// Target 1: user search
const [debouncedUserSearchQuery, setDebouncedUserSearchQuery] = useState("")
useEffect(() => {
  const timer = window.setTimeout(() => setDebouncedUserSearchQuery(userSearchQuery), SEARCH_DEBOUNCE_MS)
  return () => window.clearTimeout(timer)
}, [userSearchQuery])

// Target 2: dataset search
const [debouncedDatasetSearchQuery, setDebouncedDatasetSearchQuery] = useState("")
useEffect(() => {
  const timer = window.setTimeout(() => setDebouncedDatasetSearchQuery(datasetSearchQuery), SEARCH_DEBOUNCE_MS)
  return () => window.clearTimeout(timer)
}, [datasetSearchQuery])

// Target 3: grant user search
const [debouncedGrantUserSearchQuery, setDebouncedGrantUserSearchQuery] = useState("")
useEffect(() => {
  const timer = window.setTimeout(() => setDebouncedGrantUserSearchQuery(grantUserSearchQuery), SEARCH_DEBOUNCE_MS)
  return () => window.clearTimeout(timer)
}, [grantUserSearchQuery])
```

- [ ] **Step 2: Add import and replace all 3 blocks**

```typescript
import { useDebounce } from '../../lib/useDebounce'
// ...
const debouncedUserSearchQuery = useDebounce(userSearchQuery, SEARCH_DEBOUNCE_MS)
const debouncedDatasetSearchQuery = useDebounce(datasetSearchQuery, SEARCH_DEBOUNCE_MS)
const debouncedGrantUserSearchQuery = useDebounce(grantUserSearchQuery, SEARCH_DEBOUNCE_MS)
```

Delete all 3 `useState` declarations and all 3 `useEffect` blocks for these 3 variables.

- [ ] **Step 3: Verify lsp_diagnostics clean**

- [ ] **Step 4: Verify success criteria**

```bash
grep "setDebouncedUserSearchQuery\|setDebouncedDatasetSearchQuery\|setDebouncedGrantUserSearchQuery" \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionCenterModal.tsx
# Must print 0 lines
grep "import.*useDebounce" \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionCenterModal.tsx
# Must print 1 line
```

### DatasetConfigStep.tsx

- [ ] **Step 5: Read the file, locate the 2 debounce blocks, apply same pattern**

```typescript
import { useDebounce } from '../../lib/useDebounce'
// Replace each useState + useEffect debounce pair with a single useDebounce call
```

- [ ] **Step 6: Verify lsp_diagnostics clean**

- [ ] **Step 7: Verify success criteria**

```bash
grep "window\.setTimeout\|window\.clearTimeout\|setTimeout\|clearTimeout" \
  pathlab/pathlab-client/src/renderer/src/components/upload/DatasetConfigStep.tsx
# Must print 0 lines
grep "import.*useDebounce" \
  pathlab/pathlab-client/src/renderer/src/components/upload/DatasetConfigStep.tsx
# Must print 1 line
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

**Migration pattern for each file:**

1. Add import: `import { useConfirmDialog } from '../lib/useConfirmDialog'`
2. Find and delete the local `useState<ConfirmDialogState>(...)` declaration
3. Find and delete the local `showConfirmDialog` and `closeConfirmDialog` handler functions
4. Replace with: `const { dialogState, showConfirmDialog, closeConfirmDialog } = useConfirmDialog()`
5. Ensure the JSX renders `<ConfirmDialog dialog={dialogState} onClose={closeConfirmDialog} />` (it likely already does — just verify the variable names match)

- [ ] **Step 1: Migrate `pages/ListPage.tsx`** — read the file, locate ConfirmDialogState usage, apply migration pattern

- [ ] **Step 2: Verify lsp_diagnostics clean**

- [ ] **Step 3: Migrate `pages/TaskListPage.tsx`**

- [ ] **Step 4: Migrate `pages/TaskDetailPage.tsx`**

- [ ] **Step 5: Migrate `pages/NewTaskPage.tsx`**

- [ ] **Step 6: Verify lsp_diagnostics clean on all 4 files**

- [ ] **Step 7: Verify success criteria**

```bash
for f in ListPage.tsx TaskListPage.tsx TaskDetailPage.tsx NewTaskPage.tsx; do
  echo "=== $f ==="
  grep "useState<ConfirmDialogState>" "pathlab/pathlab-client/src/renderer/src/pages/${f}"
  # Must print 0 lines per file
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

## Task 7: Roll Out useConfirmDialog — Settings Components (7 files)

**Files to modify:**
- `components/settings/UsersTab.tsx`
- `components/settings/StorageTab.tsx`
- `components/settings/ModelsTab.tsx`
- `components/settings/AnnotationAuditCard.tsx`
- `components/settings/DatasetPermissionModal.tsx`
- `components/settings/PermissionModal.tsx`
- `components/settings/PermissionCenterModal.tsx` ← **special case** (see note)

**Note on PermissionCenterModal:** This component currently receives `showConfirmDialog` and `closeConfirmDialog` as **props** from its parent (`SettingsPage`). Do NOT adopt the hook in this modal itself — instead, the **parent** (`SettingsPage.tsx` or whatever mounts `PermissionCenterModal`) adopts the hook and passes the functions down. The modal's prop interface is unchanged. If `SettingsPage.tsx` is the parent, add the hook there.

**Migration pattern:** Same as Task 6.

- [ ] **Step 1: Locate the parent that mounts `PermissionCenterModal` and add `useConfirmDialog` there**

```bash
grep -r "PermissionCenterModal" pathlab/pathlab-client/src/renderer/src --include="*.tsx" -l
```

- [ ] **Step 2: Migrate `components/settings/UsersTab.tsx`**

- [ ] **Step 3: Migrate `components/settings/StorageTab.tsx`**

- [ ] **Step 4: Migrate `components/settings/ModelsTab.tsx`**

- [ ] **Step 5: Migrate `components/settings/AnnotationAuditCard.tsx`**

- [ ] **Step 6: Migrate `components/settings/DatasetPermissionModal.tsx`**

- [ ] **Step 7: Migrate `components/settings/PermissionModal.tsx`**

- [ ] **Step 8: Verify lsp_diagnostics clean on all modified files**

- [ ] **Step 9: Commit**

```bash
git add \
  pathlab/pathlab-client/src/renderer/src/components/settings/UsersTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/StorageTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/ModelsTab.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/AnnotationAuditCard.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/DatasetPermissionModal.tsx \
  pathlab/pathlab-client/src/renderer/src/components/settings/PermissionModal.tsx
# Include SettingsPage.tsx if modified
git commit -m "refactor: migrate settings components to useConfirmDialog hook"
```

---

## Task 8: Roll Out useAsyncAction — Pages (6 files)

**Files to modify:**
- `pages/StorageManagementPage.tsx`
- `pages/TaskDetailPage.tsx`
- `pages/TaskListPage.tsx`
- `pages/ResultsViewerPage.tsx`
- `pages/NewTaskPage.tsx`
- `pages/AIChatPage.tsx`

**Migration pattern:**

```typescript
// BEFORE: manual loading state
const [loading, setLoading] = useState(false)
const [error, setError] = useState<string | null>(null)

const detectOrphaned = async () => {
  setLoading(true)
  setError(null)
  try {
    const data = await detectOrphanedFiles()
    setOrphanedFiles(data)
  } catch (err) {
    setError(err instanceof Error ? err.message : t('error'))
  } finally {
    setLoading(false)
  }
}

// AFTER: useAsyncAction
import { useAsyncAction } from '../lib/useAsyncAction'

const [error, setError] = useState<string | null>(null)
const [loadingOrphaned, runDetectOrphaned] = useAsyncAction({
  onError: (err) => setError(err instanceof Error ? err.message : t('error'))
})

const detectOrphaned = () => {
  setError(null)
  return runDetectOrphaned(async () => {
    const data = await detectOrphanedFiles()
    setOrphanedFiles(data)
  })
}
```

**For files using `useToast` for errors:** if the existing catch block calls `toastError(...)` instead of `setError(...)`, use:
```typescript
const { error: toastError } = useToast()
const [isPending, run] = useAsyncAction({ onError: (err) => toastError(err instanceof Error ? err.message : 'Error') })
```

**Scope reminder:** Only migrate handlers that follow `setX(true) + try/catch/finally + setX(false)`. Do NOT touch `useQuery` fetches or `useEffect` data loads.

- [ ] **Step 1: Migrate `pages/StorageManagementPage.tsx`**

  Target handlers: `detectOrphaned`, `handleCleanup`, `startingEmptyDatasetCleanup` handler  
  Read the file first, identify each `setLoadingX(true)` block, apply migration pattern one handler at a time.

- [ ] **Step 2: Verify lsp_diagnostics clean**

- [ ] **Step 3: Migrate `pages/TaskDetailPage.tsx`** — handlers: `handleRerun`, `handleCancel`

- [ ] **Step 4: Migrate `pages/TaskListPage.tsx`** — handler: `handleDeleteTask`

- [ ] **Step 5: Migrate `pages/ResultsViewerPage.tsx`** — handlers: `runAnalysis`, `startExternalValidation`

- [ ] **Step 6: Migrate `pages/NewTaskPage.tsx`** — handlers: `handleSubmitTask` and other async handlers

- [ ] **Step 7: Migrate `pages/AIChatPage.tsx`** — async message/action handlers

- [ ] **Step 8: Verify lsp_diagnostics clean on all 6 files**

- [ ] **Step 9: Verify success criteria**

```bash
for f in StorageManagementPage.tsx TaskDetailPage.tsx TaskListPage.tsx \
          ResultsViewerPage.tsx NewTaskPage.tsx AIChatPage.tsx; do
  echo "=== $f ==="
  grep "setLoading(true)\|setIsPending(true)\|setIsLoading(true)\|setSubmitting(true)" \
    "pathlab/pathlab-client/src/renderer/src/pages/${f}"
  # Must print 0 lines per file
done
```

- [ ] **Step 10: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/pages/StorageManagementPage.tsx \
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

**Pattern:** Same as Task 8 — read each file, identify `setLoadingX(true)/try/catch/finally/setLoadingX(false)` blocks in event handlers, replace with `useAsyncAction`.

- [ ] **Step 1: Migrate all 8 settings files** (one at a time; read → identify targets → migrate → verify diagnostics)

- [ ] **Step 2: Verify lsp_diagnostics clean on all 8 files**

- [ ] **Step 3: Verify success criteria**

```bash
for f in UsersTab.tsx ModelsTab.tsx FeedbackTab.tsx TasksTab.tsx GeneralTab.tsx \
          StorageTab.tsx AnnotationAuditCard.tsx PermissionCenterModal.tsx; do
  echo "=== $f ==="
  grep "setLoading(true)\|setIsPending(true)\|setIsLoading(true)\|setSubmitting(true)" \
    "pathlab/pathlab-client/src/renderer/src/components/settings/${f}"
done
# All must print 0 lines
```

- [ ] **Step 4: Commit**

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
- For `components/WSIViewer.tsx`: `import { useAsyncAction } from '../lib/useAsyncAction'`
- For `components/wsiViewer/`, `components/chat/`, `components/settings/`: `import { useAsyncAction } from '../../lib/useAsyncAction'`

**Pattern:** Same as Tasks 8–9.

- [ ] **Step 1: Migrate all 12 files** (read → identify `setLoadingX(true)` handler patterns → migrate)

- [ ] **Step 2: Verify lsp_diagnostics clean on all 12 files**

- [ ] **Step 3: Verify success criteria** (same grep pattern as Tasks 8–9 for all 12 files)

- [ ] **Step 4: Commit**

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

**Migration pattern:**

1. Add import: `import { PaginationFooter } from '../ui/pagination-footer'` (adjust path)
2. Find the existing pagination div/component
3. Replace with:
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
4. Delete the old pagination JSX (including any local pagination variables if they become unused)

**PermissionCenterModal special step:** Delete the private `PaginationFooter` function defined inside the file (lines ~77–143), then add the import at the top.

- [ ] **Step 1: Migrate `components/settings/PermissionCenterModal.tsx`** — delete internal component, add import

- [ ] **Step 2: Verify lsp_diagnostics clean**

- [ ] **Step 3: Migrate `components/settings/UsersTab.tsx`**

- [ ] **Step 4: Migrate `components/settings/ModelsTab.tsx`**

- [ ] **Step 5: Migrate `components/settings/FeedbackTab.tsx`**

- [ ] **Step 6: Migrate `components/settings/AnnotationAuditCard.tsx`**

- [ ] **Step 7: Migrate `pages/ListPage.tsx`**

- [ ] **Step 8: Verify lsp_diagnostics clean on all 6 files**

- [ ] **Step 9: Verify success criteria**

```bash
for f in \
  "components/settings/PermissionCenterModal.tsx" \
  "components/settings/UsersTab.tsx" \
  "components/settings/ModelsTab.tsx" \
  "components/settings/FeedbackTab.tsx" \
  "components/settings/AnnotationAuditCard.tsx" \
  "pages/ListPage.tsx"; do
  grep "import.*PaginationFooter" "pathlab/pathlab-client/src/renderer/src/${f}"
  # Must print 1 line per file
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

echo "=== ModalShell: fixed inset-0 must be 0 in all 22 modal files ==="
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
  count=$(grep -c "fixed inset-0" "$BASE/$f" 2>/dev/null || echo 0)
  echo "$f: $count (expect 0)"
done

echo "=== useDebounce: setDebounced* must be 0 in PermissionCenterModal ==="
grep -c "setDebouncedUserSearchQuery\|setDebouncedDatasetSearchQuery\|setDebouncedGrantUserSearchQuery" \
  "$BASE/components/settings/PermissionCenterModal.tsx" || echo 0

echo "=== useDebounce: setTimeout must be 0 in DatasetConfigStep ==="
grep -c "setTimeout\|clearTimeout" "$BASE/components/upload/DatasetConfigStep.tsx" || echo 0

echo "=== useConfirmDialog: no useState<ConfirmDialogState> in 11 files ==="
for f in \
  pages/ListPage.tsx pages/TaskListPage.tsx pages/TaskDetailPage.tsx pages/NewTaskPage.tsx \
  components/settings/UsersTab.tsx components/settings/StorageTab.tsx \
  components/settings/ModelsTab.tsx components/settings/AnnotationAuditCard.tsx \
  components/settings/DatasetPermissionModal.tsx components/settings/PermissionModal.tsx; do
  count=$(grep -c "useState<ConfirmDialogState>" "$BASE/$f" 2>/dev/null || echo 0)
  echo "$f: $count (expect 0)"
done

echo "=== useAsyncAction: no manual setLoading(true) in 26 files ==="
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
  count=$(grep -c "setLoading(true)\|setIsPending(true)\|setIsLoading(true)\|setSubmitting(true)" "$BASE/$f" 2>/dev/null || echo 0)
  echo "$f: $count (expect 0)"
done
```

- [ ] **Step 2: Run lsp_diagnostics on the full renderer/src directory**

Check `pathlab/pathlab-client/src/renderer/src` with extension `.tsx` — ensure no new errors were introduced (pre-existing errors from unrelated files are OK to note but not fix).

- [ ] **Step 3: Commit final**

```bash
git commit --allow-empty -m "refactor: frontend deduplication complete — ModalShell, useDebounce, useConfirmDialog, useAsyncAction, PaginationFooter"
```

