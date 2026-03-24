# Redundancy Reduction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate 6 concrete redundancies in `pathlab-client` — duplicated type definitions, misplaced shared constants, and a backend Config coupling — with zero runtime behavior changes.

**Architecture:** All changes are type-level (TypeScript) or constant relocation (Python/TS). Tasks are fully independent and can be executed in any order. Each task produces a green TypeScript compile + passing test suite before commit.

**Tech Stack:** TypeScript 5, Vitest, Python, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-redundancy-reduction-design.md`

---

## File Map

| Action | Path | Change |
|---|---|---|
| **Create** | `src/renderer/src/constants/wsi.ts` | New shared constants file |
| **Modify** | `src/renderer/src/components/upload/types.ts` | Remove `DataLevel` dead export, make `UploadMode` a re-export, remove `organSources`/`organSourceKeyMap` |
| **Modify** | `src/renderer/src/components/taskDetail/types.ts` | `TaskDetail.status` → `TrainingTaskStatus` |
| **Modify** | `src/renderer/src/components/list/FileMetadataModal.tsx` | `FileMetadataMap` value type → `FileMetadata` |
| **Modify** | `src/renderer/src/components/wsiViewer/CreateDatasetDialog.tsx` | Update import to `constants/wsi` |
| **Modify** | `src/renderer/src/components/list/EditModals.tsx` | Update import to `constants/wsi` |
| **Modify** | `src/renderer/src/pages/ListPage.tsx` | Update import to `constants/wsi` |
| **Modify** | `src/renderer/src/components/chat/DatasetRegistrationCard.tsx` | Update import to `constants/wsi` |
| **Modify** | `src/renderer/src/pages/UploadPage.tsx` | Update import to `constants/wsi` |
| **Modify** | `server/gateway/dependencies.py` | Replace hardcoded URLs with `Config` |

---

## Verification Commands

Run these after every task to confirm nothing broke:

```bash
# Frontend: TypeScript type check (run from pathlab-client/)
npx tsc --noEmit

# Frontend: test suite
npm run test:run

# Backend (after Task 6 only)
python -m pytest server/tests/ -v -k "not pretrained"
```

---

## Task 1: F5 — Remove dead `DataLevel` export

**Files:**
- Modify: `src/renderer/src/components/upload/types.ts`

Context: `export type DataLevel = 'case' | 'file'` in `upload/types.ts` is not imported by any file. The literal `'case' | 'file'` is used inline in `list/EditModals.tsx` already.

- [ ] **Step 1: Verify it's truly unused**

  ```bash
  grep -rn "from.*upload/types.*DataLevel\|DataLevel.*from.*upload" \
    src/renderer/src/ --include="*.ts" --include="*.tsx"
  ```
  Expected: no output (zero matches). If you see matches, stop and read them before proceeding.

- [ ] **Step 2: Delete the dead export**

  In `src/renderer/src/components/upload/types.ts`, remove these 3 lines:
  ```typescript
  // Aggregation level type: case (case-level grouping) or file (file-level, each file independent)
  export type DataLevel = 'case' | 'file'
  ```
  (The comment on the line above it too.)

- [ ] **Step 3: Verify TypeScript still compiles**

  ```bash
  npx tsc --noEmit
  ```
  Expected: exits 0, no errors.

- [ ] **Step 4: Run tests**

  ```bash
  npm run test:run
  ```
  Expected: all tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/renderer/src/components/upload/types.ts
  git commit -m "refactor(types): remove unused DataLevel export from upload/types"
  ```

---

## Task 2: F3 — `TaskDetail.status` → use `TrainingTaskStatus`

**Files:**
- Modify: `src/renderer/src/components/taskDetail/types.ts`

Context: `TaskDetail.status` has an inline union identical to `TrainingTaskStatus` in `contexts/backgroundTask/types.ts`.

- [ ] **Step 1: Confirm the types are identical**

  Check `contexts/backgroundTask/types.ts` line 16 (the `TrainingTaskStatus` definition) and `components/taskDetail/types.ts` line 17 (the `status` field) are the same 10 values. They should be. If they differ, stop and report.

- [ ] **Step 2: Update `components/taskDetail/types.ts`**

  Add import at the top of the file (after any existing imports):
  ```typescript
  import type { TrainingTaskStatus } from '../../contexts/backgroundTask/types'
  ```

  Change the `status` field in `TaskDetail`:
  ```typescript
  // Before
  status: 'creating' | 'pending' | 'queued' | 'patching' | 'extracting' | 'training' | 'completed' | 'failed' | 'cancelled' | 'resuming'

  // After
  status: TrainingTaskStatus
  ```

- [ ] **Step 3: Verify TypeScript compiles**

  ```bash
  npx tsc --noEmit
  ```
  Expected: exits 0.

- [ ] **Step 4: Run tests**

  ```bash
  npm run test:run
  ```
  Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/renderer/src/components/taskDetail/types.ts
  git commit -m "refactor(types): use TrainingTaskStatus in TaskDetail.status"
  ```

---

## Task 3: F4 — `FileMetadataMap` value type → `FileMetadata`

**Files:**
- Modify: `src/renderer/src/components/list/FileMetadataModal.tsx`

Context: `FileMetadataModal.tsx` defines `FileMetadataMap = Map<string, { label, case_id, age, gender }>` inline. The 4-field object is identical to `FileMetadata` in `types/training.ts`.

- [ ] **Step 1: Confirm `FileMetadata` shape in `types/training.ts`**

  Open `src/renderer/src/types/training.ts` and verify `FileMetadata` has exactly these fields: `label: string`, `case_id: string`, `age: string`, `gender: string`.

- [ ] **Step 2: Update `FileMetadataModal.tsx`**

  Add import (near other imports at top of file):
  ```typescript
  import type { FileMetadata } from '../../types/training'
  ```

  Change the `FileMetadataMap` type definition:
  ```typescript
  // Before
  export type FileMetadataMap = Map<string, { label: string; case_id: string; age: string; gender: string }>

  // After
  export type FileMetadataMap = Map<string, FileMetadata>
  ```

- [ ] **Step 3: Verify TypeScript compiles**

  ```bash
  npx tsc --noEmit
  ```
  Expected: exits 0.

- [ ] **Step 4: Run tests**

  ```bash
  npm run test:run
  ```
  Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/renderer/src/components/list/FileMetadataModal.tsx
  git commit -m "refactor(types): use FileMetadata in FileMetadataMap instead of inline object"
  ```

---

## Task 4: F2 — `UploadMode` → alias for `TaskType`

**Files:**
- Modify: `src/renderer/src/components/upload/types.ts`

Context: `UploadMode = 'classification' | 'survival' | 'segmentation'` is identical to `TaskType` in `constants/training.ts`. Consumers (`BulkEditModal`, `DatasetConfigStep`, `UploadPage`) still import from `upload/types` — they don't need to change.

- [ ] **Step 1: Update `upload/types.ts`**

  Replace:
  ```typescript
  export type UploadMode = 'classification' | 'survival' | 'segmentation'
  ```
  With:
  ```typescript
  export type { TaskType as UploadMode } from '../../constants/training'
  ```

  Also add `TaskType` to the existing import from `constants/training` if it's already imported there, or add a new import line. **Check first** whether `upload/types.ts` already imports anything from `../../constants/training`. If it does, add `TaskType` to that import. If not, add the re-export line as shown above.

- [ ] **Step 2: Verify TypeScript compiles**

  ```bash
  npx tsc --noEmit
  ```
  Expected: exits 0.

- [ ] **Step 3: Verify consumers still work**

  Check the three files that import `UploadMode` from `upload/types` — they should NOT need changes:
  ```bash
  grep -n "UploadMode" \
    src/renderer/src/components/upload/BulkEditModal.tsx \
    src/renderer/src/components/upload/DatasetConfigStep.tsx \
    src/renderer/src/pages/UploadPage.tsx
  ```
  Expected: lines showing `import.*UploadMode.*from.*upload/types` — unchanged.

- [ ] **Step 4: Run tests**

  ```bash
  npm run test:run
  ```
  Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/renderer/src/components/upload/types.ts
  git commit -m "refactor(types): make UploadMode a re-export of TaskType"
  ```

---

## Task 5: F1 — Extract `organSources`/`organSourceKeyMap` to `constants/wsi.ts`

**Files:**
- Create: `src/renderer/src/constants/wsi.ts`
- Modify: `src/renderer/src/components/upload/types.ts` (remove originals)
- Modify (6 import sites):
  - `src/renderer/src/components/upload/types.ts`
  - `src/renderer/src/components/wsiViewer/CreateDatasetDialog.tsx`
  - `src/renderer/src/components/list/EditModals.tsx`
  - `src/renderer/src/components/list/FileMetadataModal.tsx`
  - `src/renderer/src/components/chat/DatasetRegistrationCard.tsx`
  - `src/renderer/src/pages/ListPage.tsx`
  - `src/renderer/src/pages/UploadPage.tsx`

Context: `organSources` (57-item string array) and `organSourceKeyMap` live in `upload/types.ts` but are imported by 5 unrelated modules (chat, list, wsiViewer, page level). Moving them to `constants/wsi.ts` breaks the cross-domain coupling.

- [ ] **Step 1: Copy the exact values from `upload/types.ts`**

  Open `src/renderer/src/components/upload/types.ts` and copy the full `organSources` array (lines starting with `export const organSources = [`) and the full `organSourceKeyMap` object. Do not retype them — copy exactly.

- [ ] **Step 2: Create `src/renderer/src/constants/wsi.ts`**

  Create new file with this structure:
  ```typescript
  /**
   * WSI-related shared constants used across upload, list, viewer, and chat domains.
   */

  export const organSources = [
    // paste the full array here exactly as it appears in upload/types.ts
  ] as const

  export const organSourceKeyMap: Record<string, string> = {
    // paste the full object here exactly as it appears in upload/types.ts
  }
  ```

  The values must be **character-for-character identical** to the originals. Do not add, remove, or reorder any entries.

- [ ] **Step 3: Update `upload/types.ts`** — replace the definitions with re-exports (temporarily, to avoid breaking imports during migration):

  Remove the `organSources` and `organSourceKeyMap` definitions and add:
  ```typescript
  export { organSources, organSourceKeyMap } from '../../constants/wsi'
  ```

  This keeps all 6 importers working without a single change to them — verify with `npx tsc --noEmit` before touching the importers.

- [ ] **Step 4: TypeScript check after Step 3**

  ```bash
  npx tsc --noEmit
  ```
  Expected: exits 0. If errors appear, fix before proceeding.

- [ ] **Step 5: Update all 6 import sites directly**

  For each file below, change `from '../upload/types'` (or the equivalent relative path) to `from '../../constants/wsi'` (adjust depth for pages/):

  | File | Old import | New import |
  |---|---|---|
  | `components/wsiViewer/CreateDatasetDialog.tsx` | `from '../upload/types'` | `from '../../constants/wsi'` |
  | `components/list/EditModals.tsx` | `from '../upload/types'` | `from '../../constants/wsi'` |
  | `components/list/FileMetadataModal.tsx` | `from '../upload/types'` | `from '../../constants/wsi'` |
  | `components/chat/DatasetRegistrationCard.tsx` | `from '../upload/types'` | `from '../../constants/wsi'` |
  | `pages/ListPage.tsx` | `from '../components/upload/types'` | `from '../constants/wsi'` |
  | `pages/UploadPage.tsx` | `from '../components/upload/types'` (for organSources) | `from '../constants/wsi'` |

  **Important for UploadPage**: `UploadPage.tsx` imports multiple things from `upload/types`. Only move `organSources` (and `generateCaseId`, `defaultMetadata` stay in `upload/types`). Split the import into two lines if needed:
  ```typescript
  import { organSources } from '../constants/wsi'
  import { defaultMetadata, generateCaseId, /* other types */ } from './types'
  ```

- [ ] **Step 6: Remove the re-export from `upload/types.ts`**

  Now that all 6 importers use `constants/wsi` directly, remove the re-export line added in Step 3:
  ```typescript
  // Delete this line:
  export { organSources, organSourceKeyMap } from '../../constants/wsi'
  ```

- [ ] **Step 7: TypeScript check**

  ```bash
  npx tsc --noEmit
  ```
  Expected: exits 0.

- [ ] **Step 8: Verify no file imports from upload/types for these constants**

  ```bash
  grep -rn "organSources\|organSourceKeyMap" \
    src/renderer/src/ --include="*.ts" --include="*.tsx" | grep "upload/types"
  ```
  Expected: no output.

- [ ] **Step 9: Run tests**

  ```bash
  npm run test:run
  ```
  Expected: all pass.

- [ ] **Step 10: Commit**

  ```bash
  git add src/renderer/src/constants/wsi.ts \
    src/renderer/src/components/upload/types.ts \
    src/renderer/src/components/wsiViewer/CreateDatasetDialog.tsx \
    src/renderer/src/components/list/EditModals.tsx \
    src/renderer/src/components/list/FileMetadataModal.tsx \
    src/renderer/src/components/chat/DatasetRegistrationCard.tsx \
    src/renderer/src/pages/ListPage.tsx \
    src/renderer/src/pages/UploadPage.tsx
  git commit -m "refactor(constants): extract organSources/organSourceKeyMap to constants/wsi.ts

  Decouples chat, list, and wsiViewer modules from upload/types.ts.
  Zero runtime behavior change — pure constant relocation."
  ```

---

## Task 6: B1 — `dependencies.py` Config coupling fix

**Files:**
- Modify: `server/gateway/dependencies.py`

Context: Lines 49–52 of `dependencies.py` re-read `AI_SERVICE_URL` and `PREPROCESSING_SERVICE_URL` from env with hardcoded default ports (6102, 6101). `Config` already owns these values via `Config.AI_SERVICE_URL` and `Config.PREPROCESSING_SERVICE_URL`. `gateway/utils.py` imports these names from `dependencies` — the exported names don't change.

- [ ] **Step 1: Confirm `Config` is already imported**

  Check `server/gateway/dependencies.py` imports. You should see:
  ```python
  from backend.common.config import Config
  ```
  If not present, add it. (It should be there — but verify.)

- [ ] **Step 2: Replace the two `os.getenv` calls**

  In `server/gateway/dependencies.py`, find and replace:
  ```python
  # Before
  AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:6102")
  PREPROCESSING_SERVICE_URL = os.getenv(
      "PREPROCESSING_SERVICE_URL", "http://127.0.0.1:6101"
  )

  # After
  AI_SERVICE_URL = Config.AI_SERVICE_URL
  PREPROCESSING_SERVICE_URL = Config.PREPROCESSING_SERVICE_URL
  ```

- [ ] **Step 3: Verify `os` import can be cleaned up (optional)**

  Check if `os` is still used elsewhere in `dependencies.py` (it's used for `env_path` on line ~33). If `os` is still needed, leave the import. Do not remove it speculatively.

- [ ] **Step 4: Run backend tests**

  Run from `pathlab-client/` directory:
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained"
  ```
  Expected: all tests pass (116 regular tests green).

- [ ] **Step 5: Verify the change**

  ```bash
  grep -n "os.getenv.*AI_SERVICE_URL\|os.getenv.*PREPROCESSING_SERVICE_URL" \
    server/gateway/dependencies.py
  ```
  Expected: no output.

- [ ] **Step 6: Commit**

  ```bash
  git add server/gateway/dependencies.py
  git commit -m "refactor(backend): use Config.AI_SERVICE_URL in dependencies.py

  Eliminates hardcoded port defaults that duplicated Config class values.
  gateway/utils.py imports unchanged."
  ```

---

## Final Verification

After all 6 tasks:

- [ ] Full TypeScript check: `npx tsc --noEmit` → exits 0
- [ ] Full frontend test suite: `npm run test:run` → all 30 files pass
- [ ] Full backend test suite: `python -m pytest server/tests/ -v -k "not pretrained"` → 116 tests pass
- [ ] No cross-domain constant imports: `grep -rn "organSources\|organSourceKeyMap" src/ --include="*.tsx" --include="*.ts" | grep "upload/types"` → empty
- [ ] No dead DataLevel: `grep -n "DataLevel" src/renderer/src/components/upload/types.ts` → empty
- [ ] No hardcoded service URLs: `grep -n 'os.getenv.*AI_SERVICE_URL\|os.getenv.*PREPROCESSING' server/gateway/dependencies.py` → empty
