# Redundancy Reduction & Cohesion Improvement — PathLab Client

**Date**: 2026-03-24  
**Scope**: `pathlab/pathlab-client/` — excludes `server/backend/deep-research/` and `pathlab/pathlab-server/`  
**Status**: Design approved, implementation plan complete

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

### Backend (chat.py)

#### P7 — `chat.py` conversation CRUD endpoints belong in a dedicated router (COHESION)

**Location**: `server/gateway/routes/chat.py` lines 3669–3808

`chat.py` currently contains 7 endpoints for conversation/message CRUD (create conversation, list conversations, get conversation, delete conversation, update message, add message, delete message). These endpoints are pure database operations — they have zero dependency on the SSE streaming machinery (`stream_ai_response`) that makes up the rest of the file.

The pattern already exists in the codebase: `chat_feedback.py`, `chat_patch_inference.py`, and `chat_pdf.py` are all dedicated routers included via `router.include_router()`. The conversation CRUD endpoints should follow the same pattern.

#### P8 — LLM call layer is interleaved with orchestration logic (COHESION)

**Location**: `server/gateway/routes/chat.py` lines 140–175 (module state) + 2282–2642 (LLM functions)

`chat.py` contains a self-contained LLM client layer mixed into the orchestration file:
- Module-level state: `_llm_http_client` (httpx client), `_vllm_cache`, `_VLLM_CACHE_TTL_OK`, `_VLLM_CACHE_TTL_FAIL_BASE`
- Dead code: `_CompatCacheKey` (line 173) and `_compat_check_cache` (lines 174–175) — defined, never used
- LLM call functions: `_get_llm_http_client`, `_stream_from_openai_compatible`, `_check_local_vllm_available`, `_call_ai_complete`, `_execute_exa_search`, `_consume_task_exception`, `_wait_for_disconnect`, `_run_or_cancel_on_disconnect`, `_deduplicate_search_results`, `_format_search_results_for_ai`
- Exception class: `ClientDisconnectedError` (line 2499)

This block (~450 lines) has a clean boundary: it provides the low-level primitives that `stream_ai_response` calls, and has no dependency on routing, database, or SSE response construction.

#### P9 — Model ranking/selection logic is interleaved with orchestration logic (COHESION)

**Location**: `server/gateway/routes/chat.py` lines ~146–2281 (private helper section)

A cluster of functions responsible for model selection and content processing is embedded in `chat.py`:
`extract_text_from_content`, `_infer_model_request_filters`, `_matches_model_request_filters`, `_matches_quick_model_request_filters`, `_format_model_filter_summary`, `_semantic_top_k_models`, `_should_use_semantic_model_ranking`, `_extract_images_from_content`, `_extract_citation_contexts`

These ~9 functions (~600 lines) constitute a coherent model-selection subsystem. Their only external dependency is `split_md_into_pages` from `chat_pdf.py` (used by `_extract_citation_contexts`).

#### P10 — `serve_pdf_image` endpoint is in the wrong file (COHESION)

**Location**: `server/gateway/routes/chat.py` lines 4601–4627

`GET /pdf-images/{url_hash}/{filename}` (the `serve_pdf_image` endpoint) is a file-serving endpoint with zero dependency on the LLM/chat machinery. `chat_pdf.py` already owns all other PDF-related logic in the codebase. This endpoint belongs there.

---

## Out of Scope (Explicit Exclusions)

| Item | Reason |
|---|---|
| `stream_ai_response` (lines 2643–3668, ~1025 lines) | Core SSE orchestration; has deep internal state dependencies — not split |
| `chat_patch_inference.py` endpoints (lines 3809–4600) | Already in their own router; no further decomposition needed |
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
// Before — no import, inline union
export interface TaskDetail {
  // ...
  status: 'creating' | 'pending' | 'queued' | 'patching' | 'extracting' | 'training' | 'completed' | 'failed' | 'cancelled' | 'resuming'
  // ...
}

// After — import and use named type
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

### C1 — Extract conversation CRUD to `chat_conversation.py` (fixes P7)

**New file**: `server/gateway/routes/chat_conversation.py`

Extract from `chat.py` the 7 conversation/message CRUD endpoints (lines 3669–3808):
- `POST /conversations` → create conversation
- `GET /conversations` → list conversations
- `GET /conversations/{id}` → get conversation
- `DELETE /conversations/{id}` → delete conversation
- `PUT /conversations/{conversation_id}/messages/{message_id}` → update message
- `POST /conversations/{id}/messages` → add message
- `DELETE /conversations/{conversation_id}/messages/{message_id}` → delete message

Required imports in `chat_conversation.py`:
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
```

In `chat.py`, add at module level:
```python
from .chat_conversation import router as chat_conversation_router
router.include_router(chat_conversation_router)
```

`gateway/main.py` does not change.

**Success criterion**: The 7 CRUD endpoints respond identically. `chat.py` shrinks by ~140 lines.

---

### C2 — Extract LLM call layer to `chat_llm_client.py` (fixes P8)

**New file**: `server/gateway/routes/chat_llm_client.py`

Extract from `chat.py`:
- Module-level constants: `_VLLM_CACHE_TTL_OK`, `_VLLM_CACHE_TTL_FAIL_BASE`
- Module-level state factory: `_llm_http_client` (lazy httpx client), `_vllm_cache`
- Exception class: `ClientDisconnectedError`
- Functions: `_get_llm_http_client`, `_stream_from_openai_compatible`, `_check_local_vllm_available`, `_call_ai_complete`, `_execute_exa_search`, `_consume_task_exception`, `_wait_for_disconnect`, `_run_or_cancel_on_disconnect`, `_deduplicate_search_results`, `_format_search_results_for_ai`

**Delete dead code** (do not carry over to `chat_llm_client.py`):
- `_CompatCacheKey` type alias (line ~173)
- `_compat_check_cache` dict (lines ~174–175)

In `chat.py`, add imports from the new module:
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

**Success criterion**: `chat.py` no longer defines `ClientDisconnectedError` or the LLM helper functions. All existing behavior unchanged. `chat.py` shrinks by ~450 lines. Dead code `_CompatCacheKey`/`_compat_check_cache` is deleted.

---

### C3 — Extract model selector to `chat_model_selector.py` (fixes P9)

**New file**: `server/gateway/routes/chat_model_selector.py`

Extract from `chat.py`:
- `extract_text_from_content`
- `_infer_model_request_filters`
- `_matches_model_request_filters`
- `_matches_quick_model_request_filters`
- `_format_model_filter_summary`
- `_semantic_top_k_models`
- `_should_use_semantic_model_ranking`
- `_extract_images_from_content`
- `_extract_citation_contexts`

`_extract_citation_contexts` uses `split_md_into_pages` from `chat_pdf.py`. Add:
```python
from .chat_pdf import split_md_into_pages
```

In `chat.py`, add imports from the new module:
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

**Success criterion**: `chat.py` no longer defines these 9 functions. All existing behavior unchanged. `chat.py` shrinks by ~600 lines.

---

### C4 — Move `serve_pdf_image` to `chat_pdf.py` (fixes P10)

**File modified**: `server/gateway/routes/chat_pdf.py`

Move the `GET /pdf-images/{url_hash}/{filename}` endpoint (lines 4601–4627 in `chat.py`) to `chat_pdf.py`.

`chat_pdf.py` already has its own `router`. The endpoint uses:
- `aiofiles` (already imported in `chat_pdf.py`)
- `HASHED_PDF_CACHE_DIR` constant (defined in `chat_pdf.py`)
- FastAPI `FileResponse`

Remove from `chat.py`. `chat_pdf.py`'s router is already included in `chat.py` via `router.include_router(chat_pdf_router)` — no routing change needed.

**Success criterion**: `chat.py` no longer defines `serve_pdf_image`. The endpoint continues to serve PDF images at the same URL path. `chat.py` shrinks by ~27 lines.

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
| C1 | `chat_conversation.py` (new), `chat.py` (remove 140 lines + include_router) | Low — pure extraction, no logic change |
| C2 | `chat_llm_client.py` (new), `chat.py` (remove ~450 lines + dead code) | Low — pure extraction + delete unused symbols |
| C3 | `chat_model_selector.py` (new), `chat.py` (remove ~600 lines) | Low — pure extraction, no logic change |
| C4 | `chat_pdf.py` (add ~27 lines), `chat.py` (remove ~27 lines) | Low — pure relocation, endpoint URL unchanged |

**Total files touched**: 16 (4 new, 12 modified)  
**`chat.py` line reduction**: 4627 → ~2660 lines (~42% reduction)  
**Zero runtime behavior changes**: All changes are type-level, constant relocation, or code extraction.

---

## Verification Checklist

- [ ] `npx tsc --noEmit` passes on `src/renderer/src/` with zero new errors
- [ ] `npm run test:run` passes (all 30 frontend test files)
- [ ] No file outside `constants/` imports `organSources` or `organSourceKeyMap` from a `components/` path
- [ ] `grep -r "DataLevel" src/renderer/src/components/upload/types.ts` returns empty
- [ ] `dependencies.py` contains no `os.getenv("AI_SERVICE_URL"` or `os.getenv("PREPROCESSING_SERVICE_URL"`
- [ ] `chat.py` no longer defines `ClientDisconnectedError`, conversation CRUD endpoints, or `serve_pdf_image`
- [ ] `chat.py` no longer contains `_CompatCacheKey` or `_compat_check_cache`
- [ ] All chat endpoints respond identically (functional regression test)
- [ ] `python -m pytest server/tests/ -v -k "not pretrained"` passes
