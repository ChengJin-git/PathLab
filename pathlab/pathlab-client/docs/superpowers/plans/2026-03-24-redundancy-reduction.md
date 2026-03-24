# Redundancy Reduction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate 10 concrete redundancies in `pathlab-client` — duplicated type definitions, misplaced shared constants, a backend Config coupling, and `chat.py` cohesion violations — with zero runtime behavior changes.

**Architecture:** Frontend tasks are type-level (TypeScript) or constant relocation; backend tasks are code extraction into new modules. All tasks are fully independent and can be executed in any order. Each task produces a green TypeScript compile or passing test suite before commit.

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
| **Create** | `server/gateway/routes/chat_conversation.py` | New router: 7 conversation/message CRUD endpoints |
| **Create** | `server/gateway/routes/chat_llm_client.py` | New helper: LLM call layer + ClientDisconnectedError |
| **Create** | `server/gateway/routes/chat_model_selector.py` | New helper: model ranking/selection functions |
| **Modify** | `server/gateway/routes/chat_pdf.py` | Add `serve_pdf_image` endpoint (moved from `chat.py`) |
| **Modify** | `server/gateway/routes/chat.py` | Remove extracted code, add `include_router` + imports |

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

---

## Task 7: C1 — Extract conversation CRUD to `chat_conversation.py`

**Files:**
- Create: `server/gateway/routes/chat_conversation.py`
- Modify: `server/gateway/routes/chat.py`

Context: 7 conversation/message CRUD endpoints (lines 3669–3808 in `chat.py`) are pure DB operations with zero dependency on SSE streaming. They belong in a dedicated router following the `chat_feedback.py` / `chat_patch_inference.py` pattern.

- [ ] **Step 1: Identify the exact 7 endpoints and their line ranges**

  In `server/gateway/routes/chat.py`, locate these endpoints:
  - `POST /conversations`
  - `GET /conversations`
  - `GET /conversations/{conversation_id}`
  - `DELETE /conversations/{conversation_id}`
  - `PUT /conversations/{conversation_id}/messages/{message_id}`
  - `POST /conversations/{conversation_id}/messages`
  - `DELETE /conversations/{conversation_id}/messages/{message_id}`

  Note the exact line ranges before moving anything.

- [ ] **Step 2: Create `chat_conversation.py`**

  Create `server/gateway/routes/chat_conversation.py` with:

  ```python
  import uuid
  from fastapi import APIRouter, HTTPException, Depends
  from sqlalchemy.ext.asyncio import AsyncSession
  from backend.database import get_db
  from backend.database.repositories import ChatRepository
  from backend.auth import current_active_user, User
  from backend.common.permissions import require_conversation_access
  from ..models import CreateConversationRequest, UpdateMessageRequest, AddMessageRequest
  from .chat_patch_inference import (
      cleanup_conversation_chat_patch_tasks,
      cleanup_chat_patch_tasks_from_message,
  )

  router = APIRouter()

  # [paste the 7 endpoint functions verbatim here]
  ```

  Copy the 7 endpoint functions **character-for-character** from `chat.py`. Do not modify any logic.

- [ ] **Step 3: Update `chat.py`**

  - Remove the 7 endpoint function definitions (lines 3669–3808).
  - At the top of `chat.py`, after existing router imports, add:
    ```python
    from .chat_conversation import router as chat_conversation_router
    ```
  - After the `router = APIRouter()` line, add:
    ```python
    router.include_router(chat_conversation_router)
    ```

- [ ] **Step 4: Run backend tests**

  ```bash
  python -m pytest server/tests/ -v -k "not pretrained"
  ```
  Expected: all 116 tests pass.

- [ ] **Step 5: Smoke check endpoint availability**

  ```bash
  python -c "
  import asyncio
  from server.gateway.app import create_app
  app = create_app()
  routes = [r.path for r in app.routes]
  assert any('/conversations' in r for r in routes), 'Conversation routes missing!'
  print('OK:', [r for r in routes if '/conversations' in r])
  "
  ```
  Expected: conversation routes listed.

- [ ] **Step 6: Commit**

  ```bash
  git add server/gateway/routes/chat_conversation.py server/gateway/routes/chat.py
  git commit -m "refactor(chat): extract conversation CRUD to chat_conversation.py

  Moves 7 conversation/message endpoints (~140 lines) to a dedicated router.
  No logic changes — pure extraction following chat_feedback.py pattern."
  ```

---

## Task 8: C4 — Move `serve_pdf_image` to `chat_pdf.py`

**Files:**
- Modify: `server/gateway/routes/chat_pdf.py`
- Modify: `server/gateway/routes/chat.py`

Context: `GET /pdf-images/{url_hash}/{filename}` lives in `chat.py` (lines 4601–4627) but belongs with all other PDF logic in `chat_pdf.py`. Doing C4 before C2/C3 keeps `chat.py` cleaner for the larger extractions.

- [ ] **Step 1: Locate `serve_pdf_image` in `chat.py`**

  Find the `serve_pdf_image` endpoint (around line 4601–4627). Note its exact decorator, dependencies, and any constants it uses (should only use `HASHED_PDF_CACHE_DIR` and `aiofiles`).

- [ ] **Step 2: Move the endpoint to `chat_pdf.py`**

  Append the `serve_pdf_image` function to `server/gateway/routes/chat_pdf.py` — after all existing code. The function's `@router.get(...)` decorator should target `chat_pdf.py`'s existing `router`.

  Verify that `aiofiles`, `FileResponse`, and `HASHED_PDF_CACHE_DIR` are already imported/defined in `chat_pdf.py`. Add any missing imports.

- [ ] **Step 3: Remove from `chat.py`**

  Delete the `serve_pdf_image` function and its decorator from `chat.py`.

  Verify `chat_pdf.py`'s router is already included in `chat.py` (look for `router.include_router(chat_pdf_router)` or similar). If not, add it.

- [ ] **Step 4: Run backend tests**

  ```bash
  python -m pytest server/tests/ -v -k "not pretrained"
  ```
  Expected: all 116 tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add server/gateway/routes/chat_pdf.py server/gateway/routes/chat.py
  git commit -m "refactor(chat): move serve_pdf_image endpoint to chat_pdf.py

  Consolidates all PDF-related logic in chat_pdf.py.
  No logic changes — pure relocation."
  ```

---

## Task 9: C2 — Extract LLM call layer to `chat_llm_client.py`

**Files:**
- Create: `server/gateway/routes/chat_llm_client.py`
- Modify: `server/gateway/routes/chat.py`

Context: LLM client state and call functions (~450 lines) are mixed into `chat.py`. Dead code (`_CompatCacheKey`, `_compat_check_cache`) is also deleted here.

- [ ] **Step 1: Identify all symbols to extract**

  In `chat.py`, locate:
  - Constants: `_VLLM_CACHE_TTL_OK`, `_VLLM_CACHE_TTL_FAIL_BASE`
  - Module state: `_llm_http_client`, `_vllm_cache` (the lazy httpx client and vllm availability cache)
  - Dead code to DELETE (do NOT copy): `_CompatCacheKey`, `_compat_check_cache`
  - Exception class: `ClientDisconnectedError`
  - Functions: `_get_llm_http_client`, `_stream_from_openai_compatible`, `_check_local_vllm_available`, `_call_ai_complete`, `_execute_exa_search`, `_consume_task_exception`, `_wait_for_disconnect`, `_run_or_cancel_on_disconnect`, `_deduplicate_search_results`, `_format_search_results_for_ai`

- [ ] **Step 2: Create `chat_llm_client.py`**

  Create `server/gateway/routes/chat_llm_client.py`. Include only the live code (no dead code). Required imports will depend on what the extracted functions use — read the function bodies and add exactly what's needed (likely: `httpx`, `asyncio`, `logging`, backend config/models imports).

- [ ] **Step 3: Delete dead code from `chat.py`**

  Remove `_CompatCacheKey` and `_compat_check_cache` from `chat.py`. Do not copy them to `chat_llm_client.py`.

- [ ] **Step 4: Remove extracted symbols from `chat.py`, add imports**

  Remove the extracted constants, state, class, and functions from `chat.py`.

  Add import block in `chat.py`:
  ```python
  from .chat_llm_client import (
      ClientDisconnectedError,
      _get_llm_http_client,
      _stream_from_openai_compatible,
      _check_local_vllm_available,
      _call_ai_complete,
      _execute_exa_search,
      _consume_task_exception,
      _wait_for_disconnect,
      _run_or_cancel_on_disconnect,
      _deduplicate_search_results,
      _format_search_results_for_ai,
  )
  ```

- [ ] **Step 5: Run backend tests**

  ```bash
  python -m pytest server/tests/ -v -k "not pretrained"
  ```
  Expected: all 116 tests pass.

- [ ] **Step 6: Verify dead code is gone**

  ```bash
  grep -n "_CompatCacheKey\|_compat_check_cache" server/gateway/routes/chat.py server/gateway/routes/chat_llm_client.py
  ```
  Expected: no output.

- [ ] **Step 7: Commit**

  ```bash
  git add server/gateway/routes/chat_llm_client.py server/gateway/routes/chat.py
  git commit -m "refactor(chat): extract LLM call layer to chat_llm_client.py

  Moves ClientDisconnectedError, LLM state, and 10 helper functions (~450 lines)
  to a dedicated module. Also deletes dead code: _CompatCacheKey, _compat_check_cache."
  ```

---

## Task 10: C3 — Extract model selector to `chat_model_selector.py`

**Files:**
- Create: `server/gateway/routes/chat_model_selector.py`
- Modify: `server/gateway/routes/chat.py`

Context: 9 model ranking/selection functions (~600 lines) are interleaved in `chat.py`. `_extract_citation_contexts` depends on `split_md_into_pages` from `chat_pdf.py`.

- [ ] **Step 1: Identify all 9 functions to extract**

  In `chat.py`, locate:
  - `extract_text_from_content`
  - `_infer_model_request_filters`
  - `_matches_model_request_filters`
  - `_matches_quick_model_request_filters`
  - `_format_model_filter_summary`
  - `_semantic_top_k_models`
  - `_should_use_semantic_model_ranking`
  - `_extract_images_from_content`
  - `_extract_citation_contexts`

  Note: `_extract_citation_contexts` calls `split_md_into_pages` — verify this is defined in `chat_pdf.py`.

- [ ] **Step 2: Create `chat_model_selector.py`**

  Create `server/gateway/routes/chat_model_selector.py`. Add at minimum:
  ```python
  from .chat_pdf import split_md_into_pages
  ```
  Plus any other imports the 9 functions require (read their bodies: likely `re`, `math`, `Counter`, backend model/config types).

  Copy the 9 functions **character-for-character** from `chat.py`.

- [ ] **Step 3: Remove from `chat.py`, add imports**

  Remove the 9 functions from `chat.py`.

  Add import block in `chat.py`:
  ```python
  from .chat_model_selector import (
      extract_text_from_content,
      _infer_model_request_filters,
      _matches_model_request_filters,
      _matches_quick_model_request_filters,
      _format_model_filter_summary,
      _semantic_top_k_models,
      _should_use_semantic_model_ranking,
      _extract_images_from_content,
      _extract_citation_contexts,
  )
  ```

- [ ] **Step 4: Run backend tests**

  ```bash
  python -m pytest server/tests/ -v -k "not pretrained"
  ```
  Expected: all 116 tests pass.

- [ ] **Step 5: Verify `chat.py` line count**

  ```bash
  wc -l server/gateway/routes/chat.py
  ```
  Expected: ~2660 lines (±50). If significantly higher, check for leftovers.

- [ ] **Step 6: Commit**

  ```bash
  git add server/gateway/routes/chat_model_selector.py server/gateway/routes/chat.py
  git commit -m "refactor(chat): extract model selector to chat_model_selector.py

  Moves 9 model ranking/selection functions (~600 lines) to a dedicated module.
  No logic changes — pure extraction."
  ```

---

## Final Verification

After all 10 tasks:

- [ ] Full TypeScript check: `npx tsc --noEmit` → exits 0
- [ ] Full frontend test suite: `npm run test:run` → all 30 files pass
- [ ] Full backend test suite: `python -m pytest server/tests/ -v -k "not pretrained"` → 116 tests pass
- [ ] No cross-domain constant imports: `grep -rn "organSources\|organSourceKeyMap" src/ --include="*.tsx" --include="*.ts" | grep "upload/types"` → empty
- [ ] No dead DataLevel: `grep -n "DataLevel" src/renderer/src/components/upload/types.ts` → empty
- [ ] No hardcoded service URLs: `grep -n 'os.getenv.*AI_SERVICE_URL\|os.getenv.*PREPROCESSING' server/gateway/dependencies.py` → empty
- [ ] Dead code gone: `grep -n "_CompatCacheKey\|_compat_check_cache" server/gateway/routes/chat.py` → empty
- [ ] `chat.py` shrunk: `wc -l server/gateway/routes/chat.py` → ~2660 lines
