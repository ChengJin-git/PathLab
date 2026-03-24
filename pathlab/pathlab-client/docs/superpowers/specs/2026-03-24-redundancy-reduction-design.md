# Redundancy Reduction & Cohesion Improvement — PathLab Client

**Date**: 2026-03-24  
**Scope**: `pathlab/pathlab-client/` — excludes `server/backend/deep-research/` and `pathlab/pathlab-server/`  
**Status**: Design approved, pending implementation plan

---

## Background

A full-codebase audit identified a set of contained, verifiable redundancy issues across the frontend (TypeScript) and backend (Python) layers. None of these require architectural redesign — they are precise removals of duplication and misplaced code. No runtime logic is touched.

---

## Problem Inventory

### Frontend

#### P1 — `organSources` / `organSourceKeyMap` live in the wrong module (COUPLING)

**Location**: `src/renderer/src/components/upload/types.ts`

`organSources` (57-item string array) and `organSourceKeyMap` (57-entry object) are defined inside an upload component's type file, but are consumed by 5 completely unrelated modules:

| Importer | Domain |
|---|---|
| `components/wsiViewer/CreateDatasetDialog.tsx` | WSI viewer |
| `components/list/EditModals.tsx` | Dataset list |
| `components/list/FileMetadataModal.tsx` | Dataset list |
| `components/chat/DatasetRegistrationCard.tsx` | Chat |
| `pages/ListPage.tsx` | Page layer |

This forces the viewer, list, and chat modules to import from the upload domain's internal file — a direct coupling violation.

#### P2 — `UploadMode` duplicates `TaskType` (DUPLICATION)

| Symbol | Location | Value |
|---|---|---|
| `TaskType` | `constants/training.ts` | `'classification' \| 'survival' \| 'segmentation'` |
| `UploadMode` | `components/upload/types.ts` | `'classification' \| 'survival' \| 'segmentation'` |

Identical union. Three files import `UploadMode`: `BulkEditModal.tsx`, `DatasetConfigStep.tsx`, `UploadPage.tsx`.

#### P3 — `TaskDetail.status` inlines `TrainingTaskStatus` (DUPLICATION)

| Symbol | Location | Value |
|---|---|---|
| `TrainingTaskStatus` | `contexts/backgroundTask/types.ts` L16 | `'creating' \| 'pending' \| 'queued' \| 'resuming' \| 'patching' \| 'extracting' \| 'training' \| 'completed' \| 'failed' \| 'cancelled'` |
| `TaskDetail.status` | `components/taskDetail/types.ts` L17 | same 10 values, identical |

`TaskDetail.status` is defined as an inline union literal instead of referencing the existing named type.

#### P4 — `FileMetadataMap` in list module duplicates `FileMetadata` base type (DUPLICATION)

| Symbol | Location | Shape |
|---|---|---|
| `FileMetadata` | `types/training.ts` | `{ label, case_id, age, gender }` |
| `FileMetadataMap` inline | `components/list/FileMetadataModal.tsx` L7 | `Map<string, { label, case_id, age, gender }>` |

The inner object type is identical to `FileMetadata` in `types/training.ts`.

#### P5 — Dead `DataLevel` export in `upload/types.ts` (DEAD CODE)

`components/upload/types.ts` exports `type DataLevel = 'case' | 'file'` but no file in the codebase imports it by name. The literal `'case' | 'file'` is used inline in `list/EditModals.tsx` instead.

---

### Backend

#### P6 — `dependencies.py` re-reads env vars that `Config` already owns (COUPLING)

**Location**: `server/gateway/dependencies.py` lines 49–52

```python
# Current — bypasses Config, hardcodes default port numbers
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:6102")
PREPROCESSING_SERVICE_URL = os.getenv(
    "PREPROCESSING_SERVICE_URL", "http://127.0.0.1:6101"
)
```

`backend/common/config.py` already defines both:
```python
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", f"http://127.0.0.1:{DEFAULT_AI_PORT}")
PREPROCESSING_SERVICE_URL = os.getenv(
    "PREPROCESSING_SERVICE_URL", f"http://127.0.0.1:{DEFAULT_PREPROCESSING_PORT}"
)
```

`Config` is already imported in `dependencies.py`. The hardcoded fallback port numbers (`6102`, `6101`) are duplicate references to `Config.DEFAULT_AI_PORT` and `Config.DEFAULT_PREPROCESSING_PORT`. If the defaults change in `Config`, `dependencies.py` silently diverges.

`gateway/utils.py` imports `AI_SERVICE_URL, PREPROCESSING_SERVICE_URL` from `dependencies.py` — the interface does not change.

---

## Out of Scope (Explicit Exclusions)

| Item | Reason |
|---|---|
| `gateway/routes/chat.py` (4627 lines) | Already had 6 helper modules extracted; further decomposition requires SSE flow restructuring — separate effort |
| `gateway/routes/` subdirectory reorganization | Prefix-based naming (`chat_*`, `analysis_*`, `inference_*`) already provides grouping; file moves bring no functional gain |
| Renaming `constants/training.ts` `DataLevel` | The naming conflict is with dead code (P5); renaming would ripple through 3 actively-used hooks/components unnecessarily |

---

## Proposed Changes

### F1 — Extract shared WSI constants to `constants/wsi.ts` (fixes P1)

**New file**: `src/renderer/src/constants/wsi.ts`

Move from `components/upload/types.ts`:
- `organSources: readonly string[]`
- `organSourceKeyMap: Record<string, string>`

**Update 6 import sites** to import from `../../constants/wsi` (or equivalent relative path):
1. `components/upload/types.ts` — update or re-export
2. `components/wsiViewer/CreateDatasetDialog.tsx`
3. `components/list/EditModals.tsx`
4. `components/list/FileMetadataModal.tsx`
5. `components/chat/DatasetRegistrationCard.tsx`
6. `pages/ListPage.tsx`

`upload/types.ts` can re-export for backward compatibility during migration, then remove the re-export.

**Success criterion**: No file outside `constants/` imports `organSources` or `organSourceKeyMap` from a `components/` path.

---

### F2 — Make `UploadMode` an alias for `TaskType` (fixes P2)

**File**: `src/renderer/src/components/upload/types.ts`

```typescript
// Before
export type UploadMode = 'classification' | 'survival' | 'segmentation'

// After
export type { TaskType as UploadMode } from '../../constants/training'
```

Three consumers (`BulkEditModal.tsx`, `DatasetConfigStep.tsx`, `UploadPage.tsx`) continue to import `UploadMode` from `upload/types` — no changes required at those sites.

**Success criterion**: `UploadMode` definition is a single re-export, not a separate union literal.

---

### F3 — Use `TrainingTaskStatus` in `TaskDetail.status` (fixes P3)

**File**: `src/renderer/src/components/taskDetail/types.ts`

```typescript
// Before
import type { TrainingTaskStatus } from '../../contexts/backgroundTask/types'

export interface TaskDetail {
  // ...
  status: 'creating' | 'pending' | 'queued' | 'patching' | 'extracting' | 'training' | 'completed' | 'failed' | 'cancelled' | 'resuming'
  // ...
}

// After
import type { TrainingTaskStatus } from '../../contexts/backgroundTask/types'

export interface TaskDetail {
  // ...
  status: TrainingTaskStatus
  // ...
}
```

**Success criterion**: `TaskDetail.status` field type is `TrainingTaskStatus`, no inline union.

---

### F4 — Use `FileMetadata` in `FileMetadataModal`'s Map type (fixes P4)

**File**: `src/renderer/src/components/list/FileMetadataModal.tsx`

```typescript
// Before
export type FileMetadataMap = Map<string, { label: string; case_id: string; age: string; gender: string }>

// After
import type { FileMetadata } from '../../types/training'
export type FileMetadataMap = Map<string, FileMetadata>
```

**Success criterion**: `FileMetadataMap`'s value type references `FileMetadata` from `types/training.ts`.

---

### F5 — Remove dead `DataLevel` export from `upload/types.ts` (fixes P5)

**File**: `src/renderer/src/components/upload/types.ts`

Delete:
```typescript
export type DataLevel = 'case' | 'file'
```

Verify with `grep -r "DataLevel" src/` that no file imports this from `upload/types`.

**Success criterion**: `upload/types.ts` no longer exports `DataLevel`.

---

### B1 — Use `Config` in `dependencies.py` (fixes P6)

**File**: `server/gateway/dependencies.py`

```python
# Before
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:6102")
PREPROCESSING_SERVICE_URL = os.getenv(
    "PREPROCESSING_SERVICE_URL", "http://127.0.0.1:6101"
)

# After (Config already imported)
AI_SERVICE_URL = Config.AI_SERVICE_URL
PREPROCESSING_SERVICE_URL = Config.PREPROCESSING_SERVICE_URL
```

`gateway/utils.py` imports these two names from `dependencies` — the exported names remain identical, no downstream changes needed.

**Success criterion**: `dependencies.py` has no `os.getenv` calls for service URLs; both derive from `Config`.

---

## Change Summary

| ID | File(s) touched | Risk |
|---|---|---|
| F1 | `constants/wsi.ts` (new), `upload/types.ts`, 5 import sites | Low — pure constant relocation |
| F2 | `upload/types.ts` only | Low — type alias, zero runtime effect |
| F3 | `components/taskDetail/types.ts` only | Low — type import, zero runtime effect |
| F4 | `components/list/FileMetadataModal.tsx` only | Low — type import, zero runtime effect |
| F5 | `components/upload/types.ts` only | Low — removing unused export |
| B1 | `server/gateway/dependencies.py` only | Low — same env var read, via Config |

**Total files touched**: 10 (1 new, 9 modified)  
**Zero runtime behavior changes**: All changes are type-level or constant relocation.

---

## Verification Checklist

- [ ] `npx tsc --noEmit` passes on `src/renderer/src/` with zero new errors
- [ ] `npm run test:run` passes (all 30 frontend test files)
- [ ] No file outside `constants/` imports `organSources` or `organSourceKeyMap` from a `components/` path
- [ ] `grep -r "DataLevel" src/renderer/src/components/upload/types.ts` returns empty
- [ ] `dependencies.py` contains no `os.getenv("AI_SERVICE_URL"` or `os.getenv("PREPROCESSING_SERVICE_URL"`
- [ ] `python -m pytest server/tests/ -v -k "not pretrained"` passes
