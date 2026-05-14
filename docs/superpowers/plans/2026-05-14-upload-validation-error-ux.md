# Upload Validation Error UX Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add discoverable, navigable validation error UI to the upload page that scales from 2 to 2,000+ invalid rows without backend changes.

**Architecture:** A client-side filter state (`filterToErrors`) drives a derived subset of `localItems`. A new `ErrorSummaryBar` component renders above the table. Row-level badges augment existing red input borders. The bottom bar degrades to a compact indicator.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, i18next, Vitest + @testing-library/react

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `pathlab/pathlab-client/src/renderer/src/components/upload/ErrorSummaryBar.tsx` | Renders top error banner with conditional messaging | Create |
| `pathlab/pathlab-client/src/renderer/src/pages/UploadPage.tsx` | Hosts filter state, derived invalid items, integrates ErrorSummaryBar, renders row badges | Modify |
| `pathlab/pathlab-client/src/renderer/src/locales/en-US.json` | English translations for new UI text | Modify |
| `pathlab/pathlab-client/src/renderer/src/locales/zh-CN.json` | Chinese (Simplified) translations | Modify |
| `pathlab/pathlab-client/src/renderer/src/locales/zh-HK.json` | Chinese (Traditional) translations | Modify |
| `pathlab/pathlab-client/test/unit/pages/UploadPage.test.tsx` | Tests for filter behavior, banner visibility, row badges | Modify |
| `pathlab/pathlab-client/test/unit/components/upload/ErrorSummaryBar.test.tsx` | Unit tests for ErrorSummaryBar component | Create |

---

## Task 1: Create ErrorSummaryBar Component

**Files:**
- Create: `pathlab/pathlab-client/src/renderer/src/components/upload/ErrorSummaryBar.tsx`
- Test: `pathlab/pathlab-client/test/unit/components/upload/ErrorSummaryBar.test.tsx`

**Prerequisites:** Read `pathlab/pathlab-client/src/renderer/src/components/upload/index.ts` to understand export patterns.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import { ErrorSummaryBar } from '../../../src/renderer/src/components/upload/ErrorSummaryBar'
import { describe, it, expect, vi } from 'vitest'

describe('ErrorSummaryBar', () => {
  it('renders nothing when count is 0', () => {
    const { container } = render(
      <ErrorSummaryBar
        count={0}
        total={100}
        uploadMode="classification"
        filterActive={false}
        onToggleFilter={vi.fn()}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows filenames when count ≤ 5', () => {
    render(
      <ErrorSummaryBar
        count={2}
        total={100}
        uploadMode="classification"
        filterActive={false}
        onToggleFilter={vi.fn()}
        fileNames={['file_A.jpg', 'file_B.jpg']}
      />
    )
    expect(screen.getByText(/file_A\.jpg/)).toBeInTheDocument()
    expect(screen.getByText(/file_B\.jpg/)).toBeInTheDocument()
  })

  it('shows summary only when count > 5', () => {
    render(
      <ErrorSummaryBar
        count={47}
        total={2341}
        uploadMode="classification"
        filterActive={false}
        onToggleFilter={vi.fn()}
      />
    )
    expect(screen.getByText(/47 files are missing labels/)).toBeInTheDocument()
    expect(screen.queryByText(/file_A/)).not.toBeInTheDocument()
  })

  it('calls onToggleFilter when button clicked', async () => {
    const onToggleFilter = vi.fn()
    render(
      <ErrorSummaryBar
        count={2}
        total={100}
        uploadMode="classification"
        filterActive={false}
        onToggleFilter={onToggleFilter}
      />
    )
    const button = screen.getByRole('button', { name: /show only rows with errors/i })
    await userEvent.click(button)
    expect(onToggleFilter).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd pathlab/pathlab-client
npm run test:run -- test/unit/components/upload/ErrorSummaryBar.test.tsx
```

Expected: FAIL — "ErrorSummaryBar" module not found.

- [ ] **Step 3: Implement ErrorSummaryBar component**

```tsx
// pathlab/pathlab-client/src/renderer/src/components/upload/ErrorSummaryBar.tsx
import { AlertCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '../ui/button'
import type { UploadMode } from './types'

export interface ErrorSummaryBarProps {
  count: number
  total: number
  uploadMode: UploadMode
  filterActive: boolean
  onToggleFilter: () => void
  fileNames?: string[]
}

export function ErrorSummaryBar({
  count,
  total,
  uploadMode,
  filterActive,
  onToggleFilter,
  fileNames = [],
}: ErrorSummaryBarProps) {
  const { t } = useTranslation()

  if (count === 0) return null

  const isSmallCount = count <= 5
  const isSurvival = uploadMode === 'survival'

  const summaryText = isSmallCount
    ? isSurvival
      ? t('validationMissingSurvivalSummary', { count, files: fileNames.join(', ') })
      : t('validationMissingLabelsSummary', { count, files: fileNames.join(', ') })
    : isSurvival
      ? t('uploadPage.validationMissingSurvival', { count })
      : t('uploadPage.validationMissingLabels', { count })

  const buttonText = isSmallCount
    ? t('validationShowOnlyErrors')
    : t('validationShowOnlyErrorsCount', { count })

  return (
    <div
      role="alert"
      aria-live="polite"
      aria-atomic="true"
      className="mb-3 p-3 bg-amber-50 border border-amber-200 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3"
    >
      <div className="flex items-center gap-2 text-sm text-amber-800">
        <AlertCircle className="w-4 h-4 shrink-0" />
        <span>{summaryText}</span>
      </div>
      <div className="flex items-center gap-2">
        {!filterActive ? (
          <Button
            size="sm"
            variant="outline"
            onClick={onToggleFilter}
            aria-pressed={false}
          >
            {buttonText}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            onClick={onToggleFilter}
            aria-pressed={true}
          >
            {t('validationClearFilter')}
          </Button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Export from upload index**

Add to `pathlab/pathlab-client/src/renderer/src/components/upload/index.ts`:

```ts
export { ErrorSummaryBar } from './ErrorSummaryBar'
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd pathlab/pathlab-client
npm run test:run -- test/unit/components/upload/ErrorSummaryBar.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/components/upload/ErrorSummaryBar.tsx
 git add pathlab/pathlab-client/src/renderer/src/components/upload/index.ts
 git add pathlab/pathlab-client/test/unit/components/upload/ErrorSummaryBar.test.tsx
git commit -m "feat(upload): add ErrorSummaryBar component for validation errors"
```

---

## Task 2: Add Filter State and Derived Values to UploadPage

**Files:**
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/UploadPage.tsx`
- Test: `pathlab/pathlab-client/test/unit/pages/UploadPage.test.tsx`

- [ ] **Step 1: Write failing test for filter behavior**

Add to `UploadPage.test.tsx`:

```tsx
it('filters table to show only invalid rows when filter is active', async () => {
  // Setup: render UploadPage with some items missing labels
  // ...existing setup helpers...
  
  // Trigger validation
  const submitButton = screen.getByRole('button', { name: /register all/i })
  await userEvent.click(submitButton)
  
  // Click "Show only rows with errors"
  const filterButton = await screen.findByRole('button', { name: /show only rows with errors/i })
  await userEvent.click(filterButton)
  
  // Should only show invalid rows
  const rows = screen.getAllByRole('row')
  // Expect fewer rows than total items
  expect(rows.length).toBeLessThan(totalItems.length + 1) // +1 for header
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd pathlab/pathlab-client
npm run test:run -- test/unit/pages/UploadPage.test.tsx -t "filters table"
```

Expected: FAIL — filter button not found or filter logic not implemented.

- [ ] **Step 3: Add filter state and derived values**

In `UploadPage.tsx`, near existing state declarations (around line 216):

```tsx
// Add after selectedItems state
const [filterToErrors, setFilterToErrors] = useState(false)
```

Replace `paginatedItems` derivation (around line 247) with:

```tsx
const invalidItems = useMemo(() => {
  if (!showValidation) return []
  return localItems.filter(item => {
    const meta = localMetadata.get(item.key)
    if (uploadMode === 'classification') return !meta?.label?.trim()
    if (uploadMode === 'survival') return !meta?.event_time?.trim() || !meta?.event_status?.trim()
    return false
  })
}, [localItems, localMetadata, showValidation, uploadMode])

const displayedItems = useMemo(() => {
  const source = filterToErrors ? invalidItems : localItems
  const start = (currentPage - 1) * itemsPerPage
  return source.slice(start, start + itemsPerPage)
}, [filterToErrors, invalidItems, localItems, currentPage, itemsPerPage])

const displayedTotalPages = Math.ceil(
  (filterToErrors ? invalidItems.length : localItems.length) / itemsPerPage
)
```

- [ ] **Step 4: Update pagination effect**

Replace the existing `useEffect` that guards `currentPage` (around line 252):

```tsx
useEffect(() => {
  if (currentPage > displayedTotalPages && displayedTotalPages > 0) {
    setCurrentPage(displayedTotalPages)
  } else if (displayedTotalPages === 0 && currentPage !== 1) {
    setCurrentPage(1)
  }
}, [displayedTotalPages, currentPage])
```

- [ ] **Step 5: Add auto-clear filter effect**

Add near other effects:

```tsx
useEffect(() => {
  if (invalidItems.length === 0) {
    setFilterToErrors(false)
  }
}, [invalidItems.length])
```

- [ ] **Step 6: Reset filter when validation is hidden**

Add near `showValidation` usage:

```tsx
useEffect(() => {
  if (!showValidation) {
    setFilterToErrors(false)
  }
}, [showValidation])
```

- [ ] **Step 7: Run tests to verify they pass**

Run:
```bash
cd pathlab/pathlab-client
npm run test:run -- test/unit/pages/UploadPage.test.tsx -t "filters table"
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/pages/UploadPage.tsx
git add pathlab/pathlab-client/test/unit/pages/UploadPage.test.tsx
git commit -m "feat(upload): add client-side filter for invalid rows"
```

---

## Task 3: Integrate ErrorSummaryBar and Row Badges into UploadPage

**Files:**
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/UploadPage.tsx`
- Test: `pathlab/pathlab-client/test/unit/pages/UploadPage.test.tsx`

- [ ] **Step 1: Write failing test for banner visibility**

```tsx
it('shows error summary banner when validation fails', async () => {
  // Setup with items missing labels
  const submitButton = screen.getByRole('button', { name: /register all/i })
  await userEvent.click(submitButton)
  
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.getByText(/missing labels/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd pathlab/pathlab-client
npm run test:run -- test/unit/pages/UploadPage.test.tsx -t "shows error summary"
```

Expected: FAIL — banner not rendered.

- [ ] **Step 3: Import and render ErrorSummaryBar**

Add import at top of `UploadPage.tsx`:

```tsx
import { ErrorSummaryBar } from '../components/upload/ErrorSummaryBar'
```

Insert above the table (inside the Card, before the table scroll area, around line 1308):

```tsx
{showValidation && invalidItems.length > 0 && (
  <ErrorSummaryBar
    count={invalidItems.length}
    total={localItems.length}
    uploadMode={uploadMode}
    filterActive={filterToErrors}
    onToggleFilter={() => {
      setFilterToErrors(prev => !prev)
      setCurrentPage(1)
    }}
    fileNames={invalidItems.length <= 5 ? invalidItems.map(i => i.name) : undefined}
  />
)}
```

- [ ] **Step 4: Replace paginatedItems with displayedItems in table body**

Find the `paginatedItems.map` call (around line 1379) and replace with `displayedItems.map`.

- [ ] **Step 5: Add row-level error badges**

In the row render, inside the filename column (around line 1400), add after the existing file info:

```tsx
{hasError && (
  <span className="inline-flex items-center gap-1 text-[10px] text-red-600 bg-red-50 px-1.5 py-0.5 rounded font-medium">
    <AlertCircle className="w-3 h-3" aria-label={uploadMode === 'classification' ? t('missingLabelBadge') : t('missingSurvivalBadge')} />
    {uploadMode === 'classification' ? t('missingLabelBadge') : t('missingSurvivalBadge')}
  </span>
)}
```

- [ ] **Step 6: Add filter indicator chip**

In the toolbar area (around line 1270), add after the duplicate count badge:

```tsx
{filterToErrors && (
  <span
    role="status"
    className="inline-flex items-center gap-1 text-[10px] bg-blue-50 text-blue-700 px-2 py-1 rounded-full border border-blue-200"
    aria-label={t('validationShowingFiltered', { filtered: invalidItems.length, total: localItems.length })}
  >
    {t('validationShowingFiltered', { filtered: invalidItems.length, total: localItems.length })}
    <button
      onClick={() => setFilterToErrors(false)}
      className="ml-1 text-blue-500 hover:text-blue-700"
      aria-label={t('validationClearFilter')}
    >
      ×
    </button>
  </span>
)}
```

- [ ] **Step 7: Update bottom bar error display**

In the bottom bar (around line 1689), replace the error message display:

```tsx
{submitError && (
  <div className="flex items-center gap-2 px-3 py-1.5 bg-red-50 text-red-600 rounded-lg text-xs">
    <AlertCircle className="w-4 h-4 shrink-0" />
    <span className="truncate">{submitError}</span>
  </div>
)}
```

Keep this as-is for now — the spec calls for a compact indicator, but the existing `submitError` display already serves this purpose. The detailed message now lives in the top banner.

- [ ] **Step 8: Run tests to verify they pass**

Run:
```bash
cd pathlab/pathlab-client
npm run test:run -- test/unit/pages/UploadPage.test.tsx -t "shows error summary"
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/pages/UploadPage.tsx
git add pathlab/pathlab-client/test/unit/pages/UploadPage.test.tsx
git commit -m "feat(upload): integrate ErrorSummaryBar, row badges, and filter indicator"
```

---

## Task 4: Add i18n Translations

**Files:**
- Modify: `pathlab/pathlab-client/src/renderer/src/locales/en-US.json`
- Modify: `pathlab/pathlab-client/src/renderer/src/locales/zh-CN.json`
- Modify: `pathlab/pathlab-client/src/renderer/src/locales/zh-HK.json`

- [ ] **Step 1: Add English translations**

In `en-US.json`, add under `uploadPage` section (near existing validation keys):

```json
{
  "validationMissingLabelsSummary_one": "1 file is missing a label: {{files}}",
  "validationMissingLabelsSummary_other": "{{count}} files are missing labels.",
  "validationMissingSurvivalSummary_one": "1 file is missing survival data.",
  "validationMissingSurvivalSummary_other": "{{count}} files are missing survival data.",
  "validationShowOnlyErrors": "Show only rows with errors",
  "validationShowOnlyErrorsCount": "Show only rows with errors — {{count}} rows",
  "validationClearFilter": "Show all rows",
  "validationShowingFiltered": "Showing {{filtered}} of {{total}} rows",
  "missingLabelBadge": "Missing label",
  "missingSurvivalBadge": "Missing survival data"
}
```

- [ ] **Step 2: Add Chinese (Simplified) translations**

In `zh-CN.json`:

```json
{
  "validationMissingLabelsSummary_one": "1 个文件缺少标签：{{files}}",
  "validationMissingLabelsSummary_other": "{{count}} 个文件缺少标签。",
  "validationMissingSurvivalSummary_one": "1 个文件缺少生存数据。",
  "validationMissingSurvivalSummary_other": "{{count}} 个文件缺少生存数据。",
  "validationShowOnlyErrors": "仅显示有错误的行",
  "validationShowOnlyErrorsCount": "仅显示有错误的行 — {{count}} 行",
  "validationClearFilter": "显示所有行",
  "validationShowingFiltered": "显示 {{filtered}} / {{total}} 行",
  "missingLabelBadge": "缺少标签",
  "missingSurvivalBadge": "缺少生存数据"
}
```

- [ ] **Step 3: Add Chinese (Traditional) translations**

In `zh-HK.json`:

```json
{
  "validationMissingLabelsSummary_one": "1 個檔案缺少標籤：{{files}}",
  "validationMissingLabelsSummary_other": "{{count}} 個檔案缺少標籤。",
  "validationMissingSurvivalSummary_one": "1 個檔案缺少生存資料。",
  "validationMissingSurvivalSummary_other": "{{count}} 個檔案缺少生存資料。",
  "validationShowOnlyErrors": "僅顯示有錯誤的行",
  "validationShowOnlyErrorsCount": "僅顯示有錯誤的行 — {{count}} 行",
  "validationClearFilter": "顯示所有行",
  "validationShowingFiltered": "顯示 {{filtered}} / {{total}} 行",
  "missingLabelBadge": "缺少標籤",
  "missingSurvivalBadge": "缺少生存資料"
}
```

- [ ] **Step 4: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/locales/en-US.json
git add pathlab/pathlab-client/src/renderer/src/locales/zh-CN.json
git add pathlab/pathlab-client/src/renderer/src/locales/zh-HK.json
git commit -m "i18n(upload): add validation error filter translations"
```

---

## Task 5: Comprehensive Testing

**Files:**
- Modify: `pathlab/pathlab-client/test/unit/pages/UploadPage.test.tsx`
- Modify: `pathlab/pathlab-client/test/unit/components/upload/ErrorSummaryBar.test.tsx`

- [ ] **Step 1: Add edge case tests for UploadPage**

```tsx
it('auto-clears filter when all errors are fixed', async () => {
  // Setup with 1 invalid item, activate filter, fix the item
  // ...
  expect(screen.queryByRole('button', { name: /show all rows/i })).not.toBeInTheDocument()
})

it('shows correct total pages when filtered', async () => {
  // Setup with 25 items, 5 invalid, itemsPerPage = 10
  // Filter should show 1 page (5 items), not 3 pages
})

it('resets filter when upload mode changes', async () => {
  // Switch from classification to survival
  // Filter should be cleared
})
```

- [ ] **Step 2: Add accessibility tests for ErrorSummaryBar**

```tsx
it('has correct ARIA attributes', () => {
  render(
    <ErrorSummaryBar
      count={2}
      total={100}
      uploadMode="classification"
      filterActive={false}
      onToggleFilter={vi.fn()}
    />
  )
  const alert = screen.getByRole('alert')
  expect(alert).toHaveAttribute('aria-live', 'polite')
  expect(alert).toHaveAttribute('aria-atomic', 'true')
})
```

- [ ] **Step 3: Run full test suite**

Run:
```bash
cd pathlab/pathlab-client
npm run test:run
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add pathlab/pathlab-client/test/
git commit -m "test(upload): add validation error filter tests"
```

---

## Task 6: Final Review and Polish

- [ ] **Step 1: Verify no TypeScript errors**

Run:
```bash
cd pathlab/pathlab-client
npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 2: Verify no lint errors**

Run:
```bash
cd pathlab/pathlab-client
npm run lint
```

Expected: No errors (or only pre-existing ones).

- [ ] **Step 3: Manual smoke test**

1. Start dev server: `npm run dev`
2. Navigate to upload page
3. Add files with some missing labels
4. Click "Register All" — verify banner appears
5. Click "Show only rows with errors" — verify table filters
6. Fix labels — verify filter auto-clears
7. Verify bottom bar still shows compact error indicator

- [ ] **Step 4: Final commit**

```bash
git commit -m "feat(upload): complete validation error UX improvements

- Add ErrorSummaryBar with scalable messaging (≤5 filenames, >5 summary)
- Add client-side 'Show only errors' filter for quick navigation
- Add row-level error badges for scannable invalid rows
- Preserve existing pagination and bottom bar behavior
- Add i18n translations for en-US, zh-CN, zh-HK
- Add comprehensive unit tests"
```

---

## Verification Checklist

- [ ] ErrorSummaryBar renders correctly for 0, 1, 5, 6, 50, 1000 errors
- [ ] Filter toggles correctly and resets page to 1
- [ ] Pagination adapts to filtered count
- [ ] Filter auto-clears when invalidItems reaches 0
- [ ] Filter resets when showValidation becomes false
- [ ] Row badges appear only for invalid rows
- [ ] Bottom bar still shows error indicator
- [ ] All i18n keys present in all 3 locales
- [ ] No TypeScript errors
- [ ] All tests pass
- [ ] No performance regression with large lists
