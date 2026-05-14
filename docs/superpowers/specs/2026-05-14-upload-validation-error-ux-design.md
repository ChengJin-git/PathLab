# Upload Page Validation Error UX Design

> Date: 2026-05-14  
> Scope: Frontend only — UploadPage.tsx and related components  
> Status: Design approved, ready for implementation

---

## 1. Problem Statement

In the PathLab upload flow, users may register thousands of pathology files. Validation errors (e.g., missing labels in classification mode) are typically rare but must be resolved before submission. The current UI suffers from three issues:

1. **Poor discoverability**: The error message appears in a sticky bar at the bottom of the page. For long paginated tables, the user must scroll to see it.
2. **No navigation aid**: The message says “N files missing labels” but gives no way to locate those rows among thousands.
3. **Scalability gap**: If hundreds or thousands of rows are invalid, listing them all would overwhelm the UI.

---

## 2. Goals

- Make validation errors discoverable **without scrolling**.
- Let users **jump directly to invalid rows**.
- Keep the UI calm when only a few rows are invalid, and **gracefully degrade** when many are invalid.
- Preserve performance for lists up to 10,000+ rows (client-side only).
- Maintain accessibility (screen-reader announcements, clear focus states).

---

## 3. Non-Goals

- No backend changes.
- No new dependencies.
- No redesign of the upload flow outside the error-display surface.
- No CSV export of error reports (future enhancement).

---

## 4. Design

### 4.1 Top Error Summary Bar

A new banner is inserted **above the table** (inside the Card, before the table scroll area) whenever `showValidation === true` and at least one row is invalid.

#### Small error count (≤ 5 files)

```
┌─────────────────────────────────────────────────────────────────┐
│ ⚠️ 2 files missing labels: file_A.jpg, file_B.jpg               │
│ [Show only rows with errors]                                    │
└─────────────────────────────────────────────────────────────────┘
```

- The filenames are truncated with `title` tooltip for full name.
- The banner uses `role="alert"` and `aria-live="polite"`.

#### Large error count (> 5 files)

```
┌─────────────────────────────────────────────────────────────────┐
│ ⚠️ 47 files missing labels (out of 2,341 total).                │
│ [Show only rows with errors]                                    │
└─────────────────────────────────────────────────────────────────┘
```

- Filenames are **not** listed to avoid layout breakage.
- The total count provides context.

#### Very large error count (> 50 files)

Same as large count, but the button text changes to:

```
[Show only rows with errors — 47 rows]
```

This reinforces the scope before the user commits to the filter.

---

### 4.2 "Show Only Errors" Filter

#### Interaction

- Clicking the button sets `filterToErrors = true` and resets `currentPage` to `1`.
- The table now renders **only** rows that fail validation.
- Pagination adapts to the filtered subset.
- A secondary "Show all rows" button appears to exit the filter.

#### Visual filter indicator

When filtered, a chip appears in the toolbar:

```
Showing 47 of 2,341 rows  [×]
```

Clicking the × clears the filter.

#### Performance

- Filtering is pure client-side on `localItems` (already in memory).
- No API calls.
- `useMemo` caches the invalid-item list and the filtered slice.

---

### 4.3 Row-Level Error Badges

In addition to the existing red input borders, each invalid row gets an inline badge in the **filename column**:

```tsx
<span className="inline-flex items-center gap-1 text-[10px] text-red-600
  bg-red-50 px-1.5 py-0.5 rounded font-medium">
  <AlertCircle className="w-3 h-3" />
  Missing label
</span>
```

This makes errors scannable even when:
- The label input is scrolled out of view (horizontal overflow).
- The user is in the default (non-filtered) view and happens to land on a page with errors.

---

### 4.4 Sticky Bottom Bar (Preserved)

The existing bottom bar remains but its error message is **downgraded** to a compact icon + count:

```
[Cancel]  [⚠️ 2]  [Register All]
```

The detailed message moves to the top banner. The bottom bar keeps a red dot / count so the user still sees an error indicator when scrolled to the bottom.

---

### 4.5 Accessibility

| Element | ARIA / Behavior |
|---------|-----------------|
| Top banner | `role="alert"`, `aria-live="polite"`, `aria-atomic="true"` |
| "Show only rows with errors" button | `aria-pressed={filterToErrors}`, descriptive label |
| Filter chip | `role="status"`, `aria-label="Filtered view, 47 of 2,341 rows"` |
| Row badge | `aria-label="Missing label"` on the icon |
| Input with error | Keeps existing `aria-invalid="true"` |

---

## 5. State Changes

### New state in UploadPage

```tsx
const [filterToErrors, setFilterToErrors] = useState(false)
```

### Derived values

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

### Side effects

```tsx
useEffect(() => {
  if (currentPage > displayedTotalPages && displayedTotalPages > 0) {
    setCurrentPage(displayedTotalPages)
  }
}, [displayedTotalPages, currentPage])
```

---

## 6. UI Text (i18n)

### New keys

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

### Existing keys (kept, used in bottom bar)

- `uploadPage.validationMissingLabels`
- `uploadPage.validationMissingSurvival`

---

## 7. Component Changes

### UploadPage.tsx

| Location | Change |
|----------|--------|
| State | Add `filterToErrors` |
| Derived | Add `invalidItems`, `displayedItems`, `displayedTotalPages` |
| Table area | Insert `<ErrorSummaryBar />` above `<table>` |
| Table body | Replace `paginatedItems.map` with `displayedItems.map` |
| Row render | Add error badge in filename column when `hasError` |
| Bottom bar | Keep compact error indicator; detailed message removed from here |
| Effect | Reset `filterToErrors` when `showValidation` becomes false |

### New sub-component: ErrorSummaryBar

Props:
```tsx
interface ErrorSummaryBarProps {
  count: number
  total: number
  uploadMode: UploadMode
  filterActive: boolean
  onToggleFilter: () => void
}
```

Renders the banner described in §4.1.

---

## 8. Edge Cases

| Scenario | Behavior |
|----------|----------|
| User fixes all errors while filtered | `invalidItems` becomes empty; banner disappears; filter auto-clears (`useEffect` watches `invalidItems.length === 0`) |
| User deletes all items while filtered | Table shows empty state; "Show all rows" button visible |
| User switches upload mode | `filterToErrors` resets to `false`; validation recalculates |
| User uploads CSV that fixes labels | `localMetadata` updates; `invalidItems` recalculates; banner may disappear |
| 0 invalid rows | No banner rendered; bottom bar shows no error |
| Exactly 5 invalid rows | Uses `other` plural form; filenames **not** listed (threshold is strict `≤ 5` for listing) |

---

## 9. Testing Checklist

- [ ] Banner appears when `showValidation = true` and errors exist.
- [ ] Banner does **not** appear when `showValidation = false`.
- [ ] Clicking "Show only rows with errors" filters the table.
- [ ] Pagination updates to filtered count.
- [ ] "Show all rows" restores full list.
- [ ] Fixing all errors while filtered clears the filter and hides the banner.
- [ ] Row badge renders only for invalid rows.
- [ ] Bottom bar shows compact error count (not full message).
- [ ] Screen reader announces banner on appearance.
- [ ] No performance regression with 5,000 rows.

---

## 10. Open Questions

1. Should the error summary bar be **dismissible** (× button) or persistent until errors are fixed?  
   → **Recommendation:** Persistent. Dismissing it would hide the only clear call-to-action.

2. Should we add a "Download error report" button for > 50 errors?  
   → **Out of scope for this design.** Can be added later without breaking changes.

3. Should the filter persist across page changes within the filtered view?  
   → **Yes.** The user may need to edit errors on multiple pages. Filter clears only explicitly or when errors reach zero.

---

## 11. Effort Estimate

**Short (1–4 hours)**

- State + derived values: 15 min
- ErrorSummaryBar component: 30 min
- Table integration + row badges: 30 min
- i18n keys: 15 min
- Tests: 60 min
- Polish / review: 30 min

No backend work. No new dependencies.
