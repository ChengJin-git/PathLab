# PathLab Batch Inference on Unlabeled Datasets — Design Spec

**Date**: 2026-03-28  
**Version**: 2.1  
**Status**: Pending Final Review

---

## Changelog

| Version | Changes |
|---|---|
| 1.0 | Initial draft |
| 2.0 | Fixed all 8 Oracle-identified BLOCKERs: new inference handlers, DataGroup/task_type model, TaskType.BATCH_INFERENCE + restart recovery, atomic DB writes + revocation, normalized compatibility checks, model.is_active check, added backend task-list + CSV-export endpoints, fixed segmentation unlabeled filter. Added Chat integration section (AnalysisConfigCard + ConversationMode.BATCH_INFERENCE). Fixed 2 MINORs: SSE token-in-URL note, typos/metadata field names. |
| 2.1 | Added §4.3 i18n contract (all strings must use translation hook; keys in §9). Added §4.5 Large Dataset Mitigations: CHUNK_SIZE=50 chunked backend processing, server-enforced max limit=500 on results endpoint, frontend server-driven pagination (pageSize=100), large dataset warning banner (>2000 slides). Added i18n keys: largeDatasetWarning, showingCount, pageOf. |

---

## 1. Problem Statement

PathLab currently provides:
- **Single-WSI inference** (`POST /tasks/wsi_classification`) — one slide at a time, poor UX for datasets
- **External Validation** (`POST /results/external-validation`) — requires labeled data, computes metrics

There is no way to run a trained model over an entire dataset of unlabeled slides and retrieve per-slide predictions. Researchers routinely need to score new cohorts for which no ground truth exists.

---

## 2. Goals

- Allow users to select a trained model and an unlabeled dataset, then run batch inference over all slides in one job
- Support all three task types: **classification**, **survival analysis**, **segmentation**
- Support both data levels: **WSI** and **patch**
- Track job progress via the existing SSE infrastructure
- Display task-type-specific results in a dedicated panel within the existing Results page
- Integrate into AIChatPage via an extended `AnalysisConfigCard` component
- Strictly conform to the existing permission model (revocation checkpoints, `_require_task_access`, GPU gates, `trained_model.is_active`)

---

## 3. Non-Goals

- Computing accuracy/AUC/metrics (no ground truth available — that is External Validation's job)
- A standalone new page/route (entry lives inside the existing `/results` page)

> **Note (v2.0)**: The v1.0 non-goal of "not modifying existing inference handlers" is removed. Batch inference requires new handlers to operate on unlabeled data (no label-derived class lists). Existing handlers (`_run_inference_wsi_classification`, etc.) remain untouched; new "unlabeled" variants are added instead.

---

## 4. Architecture

### 4.1 System Overview

```
User (Results page → 批量推理 Tab  OR  AIChatPage → AnalysisConfigCard)
    │
    ▼
POST /results/batch-inference
    │  permission checks (dataset access + GPU + model access + model.is_active + compatibility)
    ▼
DataGroup(task_type="batch_inference", data_type=<target>) created
TrainingTask created, model_config stores: model_task_id, model_id, dataset_id, model_task_type, model_data_type
    │
    ▼
GPU Task Queue — TaskType.BATCH_INFERENCE (new enum value)
    │
    ▼
_run_batch_inference() [inference_batch.py]
    │  routes to NEW unlabeled inference handlers:
    ├─ WSI classification   → _run_batch_inference_wsi_classification()
    ├─ Patch classification → _run_batch_inference_patch_classification()
    ├─ Survival             → _run_batch_inference_wsi_survival()     [risk score only, no labels needed]
    └─ Patch segmentation   → _run_batch_inference_patch_segmentation()
         │
         ▼
    Results computed in-memory
    Revocation checkpoint before DB write
    bulk_create + single commit (safe_session)
    clear_revocation() in finally
         │
         ▼
AIResult rows written per WSI (existing table)
    │
    ▼
SSE via existing training task stream (TaskType.BATCH_INFERENCE recognized by restart recovery)
    │
    ▼
GET /results/batch-inference/{task_id}/results  (task-type-specific response)
    │
    ▼
BatchInferencePanel (Results page tab) — task-type-specific results table + CSV export
```

### 4.2 Backend Components

#### 4.2.1 New/Modified Models

**`gateway/task_queue.py`** — add to `TaskType` enum:
```python
class TaskType(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    EXTERNAL_VALIDATION = "external_validation"
    ANALYSIS = "analysis"
    BATCH_INFERENCE = "batch_inference"   # ← NEW
```

**`gateway/models.py`** — add Pydantic request model:
```python
class BatchInferenceRequest(BaseModel):
    model_task_id: str      # the TrainingTask that produced the model
    dataset_id: str         # target unlabeled dataset
    rerun_from_task_id: Optional[str] = None  # Admin rerun only
```

#### 4.2.2 New/Modified Endpoints in `routes/results.py`

---

**`GET /results/datasets-for-inference`**

Returns datasets suitable for batch inference. Query params:
- `unlabeled_only: bool = True` — filter logic per task type (see §4.2.2a)
- `task_type: Optional[str]` — filter by task type (to show only compatible datasets for a selected model)

Auth: same as `get_datasets_for_validation` (dataset read access). Returns same response schema as `/results/datasets-for-validation`.

Does **not** exclude `batch_inference` task_type entries (unlike extval which excludes extval datasets). Excludes datasets that are themselves pending/running batch_inference jobs for the same model (to prevent duplicate runs).

**§4.2.2a — "Unlabeled Only" semantics per task type:**

| Task Type | Unlabeled criterion |
|---|---|
| Classification (WSI or patch) | `distinct_label_count == 0` (no WSI-level labels) |
| Survival | No `wsi.survival_time` set for any slide in the dataset |
| Segmentation | No filter applied — segmentation batch inference produces masks without needing GT masks; always show all segmentation datasets |

---

**`POST /results/batch-inference`**

Permission checks (in order, mirroring `start_external_validation`):
1. Resolve `model_task` from `req.model_task_id`; call `_require_task_access(model_task, user, db)` — model ownership
2. Resolve `trained_model = model_task.trained_model`; check `trained_model.is_active` — raise `400` if not active  ← **NEW**
3. Resolve `dataset`; call `_has_external_validation_dataset_access(user, dataset, db)` — dataset read access
4. Call `check_dataset_gpu_permission(user, dataset_id, db)` — GPU gate
5. Compatibility check (see §4.2.2b below)
6. Admin rerun: if `user.is_admin() and req.rerun_from_task_id`, resolve original task owner and use it as `effective_user_id`

Creates objects (same pattern as `start_external_validation`):
```python
# 1. Create DataGroup for the batch_inference job
dg = DataGroup(
    task_type="batch_inference",
    data_type=dataset.data_group.data_type,
    aggregation_level=dataset.data_group.aggregation_level,
    user_id=effective_user_id,
)

# 2. Create TrainingTask; store all routing info in model_config
task = TrainingTask(
    task_name=f"batch_inference_{dataset.name}_{model_task.task_name}",
    status=TaskStatus.PENDING,
    user_id=effective_user_id,
    group_id=dg.id,
    model_config={
        "model_task_id": req.model_task_id,
        "model_id": str(trained_model.id),
        "dataset_id": req.dataset_id,
        "model_task_type": model_task.data_group.task_type,   # e.g. "wsi_classification"
        "model_data_type": model_task.data_group.data_type,   # e.g. "wsi"
        "model_task_canonical": _canonical_task_type(model_task.data_group.task_type),  # e.g. "classification"
    }
)
```

Submits to task queue: `task_queue.submit(task.id, TaskType.BATCH_INFERENCE, _run_batch_inference, task_id=task.id)`

Returns: `{ task_id, status, message }`

---

**§4.2.2b — Compatibility Check**

The spec defines a helper `_canonical_task_type(raw: str) -> str` that normalizes variants:

```python
def _canonical_task_type(raw: str) -> str:
    """Normalize task_type variants to canonical form."""
    _MAP = {
        "wsi_classification": "classification",
        "patch_classification": "classification",
        "wsi_survival": "survival",
        "survival": "survival",
        "segmentation": "segmentation",
        "patch_segmentation": "segmentation",
    }
    return _MAP.get(raw, raw)
```

Compatibility check (after normalization):
```python
model_canonical = _canonical_task_type(model_task.data_group.task_type)
dataset_canonical = _canonical_task_type(dataset.data_group.task_type)
if model_canonical != dataset_canonical:
    raise HTTPException(400, f"Model type '{model_canonical}' is incompatible with dataset type '{dataset_canonical}'")
# Also check data_type (wsi vs patch):
if model_task.data_group.data_type != dataset.data_group.data_type:
    raise HTTPException(400, f"Model data level '{model_task.data_group.data_type}' mismatches dataset '{dataset.data_group.data_type}'")
```

---

**`GET /results/batch-inference/{task_id}/results`**

Returns per-WSI inference results for a completed batch_inference task:
- Auth: task owner/admin (same as other task endpoints)
- Query: `AIResult JOIN WSISlide WHERE AIResult.task_id = task_id`
- Response includes `task_type` (from `task.model_config["model_task_canonical"]`) and `data_type` (from `task.data_group.data_type`) so frontend can render the correct column set
- Pagination: `skip` / `limit` params, default limit 500, max 2000

Response schema:
```json
{
  "task_type": "classification",
  "data_type": "wsi",
  "items": [
    {
      "wsi_id": "...",
      "original_filename": "slide_001.svs",
      "case_id": "CASE-001",
      "pred": "adenocarcinoma",
      "probs": { "adenocarcinoma": 0.87, "normal": 0.13 },
      "risk_score": null,
      "risk_group": null,
      "pred_mask_path": null,
      "created_at": "2026-03-28T10:00:00Z"
    }
  ],
  "total": 120
}
```
All task-type-specific fields are present but null when not applicable (unified schema, frontend switches display).

---

**`GET /results/batch-inference/tasks`**  ← **NEW (was missing in v1.0)**

Lists all batch_inference tasks visible to the requesting user:
- Auth: user sees own tasks; admin sees all
- Filter: `DataGroup.task_type == "batch_inference"` joined to `TrainingTask`
- Returns: `{ items: [{ task_id, status, dataset_name, model_name, created_at, total_wsi }], total }`
- Pagination: `skip`/`limit`, default limit 50

---

**`GET /results/batch-inference/{task_id}/export-csv`**  ← **NEW (was missing in v1.0)**

Server-side CSV streaming (avoids large in-memory arrays in browser):
- Auth: task owner/admin
- Streams CSV with `Content-Disposition: attachment; filename="batch_inference_{task_id}.csv"`
- Column set adapts to `task_type` (same fields as results endpoint)
- No pagination — streams full result set

#### 4.2.3 Task Queue — `resume_interrupted_tasks()` Update

**`gateway/main.py`** — add `batch_inference` recovery logic alongside the existing `external_validation` case:

```python
# In resume_interrupted_tasks():
elif dg.task_type == "batch_inference":
    cfg = task.model_config
    task_queue.submit(
        task.id,
        TaskType.BATCH_INFERENCE,
        _run_batch_inference,
        task_id=task.id,
        model_task_id=cfg["model_task_id"],
        model_id=cfg["model_id"],
        dataset_id=cfg["dataset_id"],
    )
```

The task queue safety net (which handles stuck INFERENCE tasks as AITask) must **not** apply to BATCH_INFERENCE tasks. Ensure the safety net check is:
```python
if task_type == TaskType.INFERENCE:   # AITask only — not BATCH_INFERENCE
    ...
```

#### 4.2.4 New File: `routes/inference_batch.py`

Contains the orchestrator plus new "unlabeled" inference handlers. These are NOT wrappers around existing handlers — they are new functions that:
- Derive class lists from `TrainedModel.classes` (not from `WSISlide.label`)
- Process slides in **chunks** (see §4.5 below) for bounded memory and frequent revocation checkpoints
- Write each chunk atomically and independently

```python
CHUNK_SIZE = 50  # slides per write batch — keeps peak memory low

async def _run_batch_inference(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    db: AsyncSession,
    progress_callback,
    assigned_device: str,
):
    """Main orchestrator — resolves resources, routes by task type, writes in chunks."""
    # 1. Resolve model and dataset
    model_task = await TrainingRepository.get_task(db, model_task_id)
    trained_model = model_task.trained_model
    dataset_wsi_ids = await DatasetRepository.get_wsi_ids(db, dataset_id)

    # 2. Pre-inference revocation check
    if is_permission_revoked(task_id):
        raise PermissionRevokedException(task_id)

    try:
        canonical = _canonical_task_type(model_task.data_group.task_type)
        data_type  = model_task.data_group.data_type

        # 3. Chunk-based processing
        for chunk_start in range(0, len(dataset_wsi_ids), CHUNK_SIZE):
            chunk_ids = dataset_wsi_ids[chunk_start : chunk_start + CHUNK_SIZE]

            # Route to correct unlabeled handler for this chunk
            if canonical == "segmentation":
                chunk_results = await _run_batch_inference_patch_segmentation(
                    trained_model, chunk_ids, db, progress_callback, assigned_device
                )
            elif canonical == "survival":
                chunk_results = await _run_batch_inference_wsi_survival(
                    trained_model, chunk_ids, db, progress_callback, assigned_device
                )
            elif data_type == "patch":
                chunk_results = await _run_batch_inference_patch_classification(
                    trained_model, chunk_ids, db, progress_callback, assigned_device
                )
            else:
                chunk_results = await _run_batch_inference_wsi_classification(
                    trained_model, chunk_ids, db, progress_callback, assigned_device
                )

            # 4. Revocation check + atomic write per chunk
            if is_permission_revoked(task_id):
                raise PermissionRevokedException(task_id)

            async with safe_session(db) as sess:
                await AIResultRepository.bulk_create(sess, chunk_results)

    finally:
        clear_revocation(task_id)
```

Each handler `_run_batch_inference_wsi_classification()` etc.:
- Accepts a **chunk** of `wsi_ids` (not the full list)
- Returns `List[AIResultCreate]` (in-memory for the chunk only — bounded to `CHUNK_SIZE` rows)
- Uses `trained_model.classes` for label-space (no dependency on `WSISlide.label`)
- Uses the model's feature extractor path from `model_task.model_config["extractor_path"]` (same as extval)
- Calls `progress_callback(chunk_start + i, total)` after each slide

#### 4.2.5 SSE Progress

No changes to SSE infrastructure. The existing training task SSE stream broadcasts all `TrainingTask` records.

**Note for implementers**: SSE auth uses `?token=<jwt>` in the URL query parameter (via `get_user_from_token_param` dependency), **not** `Authorization` header. `EventSource` in browser does not support custom headers; always append `?token=` when opening the SSE connection.

---

### 4.3 Frontend Components

> **i18n contract**: Every user-facing string in every BatchInference component **must** go through the project's existing translation hook (follow the same `useTranslation` / `t()` pattern used in `ResultsViewerPage.tsx` and other Results-page components). Hardcoded English strings are not allowed. All required keys are defined in §9; implementers must add them to all three locale files (`en-US.json`, `zh-CN.json`, `zh-HK.json`) before wiring them up in components.

#### 4.3.1 New API Client: `api/batchInference.ts`

```typescript
// Types
export type BatchInferenceTaskType = 'classification' | 'survival' | 'segmentation'
export type BatchInferenceDataType = 'wsi' | 'patch'

export interface BatchInferenceTask {
  task_id: string
  status: string
  dataset_name: string
  model_name: string
  created_at: string
  total_wsi: number
}

export interface BatchInferenceResult {
  wsi_id: string
  original_filename: string
  case_id: string | null
  // Classification
  pred?: string | null
  probs?: Record<string, number> | null
  // Survival
  risk_score?: number | null
  risk_group?: 'high' | 'low' | null
  // Segmentation
  pred_mask_path?: string | null     // ← correct field name (not pred_mask_file)
  created_at: string | null
}

export interface BatchInferenceResultsResponse {
  items: BatchInferenceResult[]
  total: number
  task_type: BatchInferenceTaskType
  data_type: BatchInferenceDataType
}

// Functions
export async function startBatchInference(
  modelTaskId: string,
  datasetId: string,
  rerunFromTaskId?: string
): Promise<{ task_id: string; status: string; message: string }>

export async function fetchDatasetsForInference(
  unlabeledOnly?: boolean,           // ← correct spelling (not unlabledOnly)
  taskType?: string
): Promise<{ items: ValidationDataset[]; total: number }>

export async function fetchBatchInferenceResults(
  taskId: string,
  options?: { skip?: number; limit?: number }
): Promise<BatchInferenceResultsResponse>

export async function getBatchInferenceTasks(
  options?: { skip?: number; limit?: number }
): Promise<{ items: BatchInferenceTask[]; total: number }>

export async function exportBatchInferenceCSV(taskId: string): Promise<void>
// Implementation: window.open(`/api/results/batch-inference/${taskId}/export-csv?token=...`)
// or fetch with blob download (same pattern as other CSV exports in the codebase)
```

#### 4.3.2 Component Tree

```
components/results/BatchInferencePanel/
├── index.tsx                          # Top-level panel, manages phase state (config/progress/results)
├── BatchInferenceConfig.tsx           # Dataset + model selectors, submit button
├── BatchInferenceProgress.tsx         # SSE-driven progress card (reuses BackgroundTaskContext)
└── BatchInferenceResults/
    ├── index.tsx                      # Switches on task_type; shared summary bar + CSV export button
    ├── ClassificationResults.tsx      # Table: filename / pred / prob bars / time
    ├── SurvivalResults.tsx            # Table: filename / risk_score / risk_group badge
    └── SegmentationResults.tsx        # Table: filename / status / mask thumbnail link
```

#### 4.3.3 ResultsViewerPage.tsx Changes

Adds a third tab to the existing Tabs component:
```tsx
<TabsTrigger value="batch_inference">批量推理</TabsTrigger>
<TabsContent value="batch_inference">
  <BatchInferencePanel />
</TabsContent>
```

No other changes to existing tab logic.

#### 4.3.4 BackgroundTaskProvider Integration

`BatchInferenceProgress` uses the existing `useBackgroundTasks()` context hook, filtering for `task_type === "batch_inference"` (stored on the task's `DataGroup.task_type`). No new SSE subscriptions needed.

---

## 5. Chat Integration (AIChatPage + AnalysisConfigCard)

### 5.1 Overview

The AI chat agent in `AIChatPage` can suggest and trigger batch inference jobs in the same way it handles internal/external validation — by emitting a structured `[ANALYSIS_CONFIG]` block that the `AnalysisConfigCard` component renders as an actionable card.

### 5.2 Backend — New `ConversationMode`

**`gateway/routes/chat_intent_policy.py`** (or wherever `ConversationMode` is defined):

Add new mode:
```python
class ConversationMode(str, Enum):
    ...
    BATCH_INFERENCE = "batch_inference"
```

Context injected when mode is `BATCH_INFERENCE`:
- Available trained models (name, task_type, data_type, is_active)
- Unlabeled datasets (name, task_type, data_type, slide_count)
- Fetched from `GET /results/batch-inference/tasks?limit=5` (recent jobs) and `GET /results/datasets-for-inference?unlabeled_only=true` at chat session start

No web search in `BATCH_INFERENCE` mode (same pattern as `INTERNAL_EVALUATION` / `EXTERNAL_EVALUATION`).

System prompt addition for `BATCH_INFERENCE` mode:
> "You are helping the user run batch inference on unlabeled datasets. When you identify a suitable model and dataset pair, emit an `[ANALYSIS_CONFIG]` block with `analysis_type: "batch_inference"`, `model_task_id`, `model_name`, `dataset_id`, and `dataset_name`. Do not suggest datasets that require labels. Do not suggest inactive models."

### 5.3 Frontend — Extended `AnalysisConfigCard`

**File**: `src/renderer/src/components/chat/AnalysisConfigCard.tsx`

#### 5.3.1 Extended Type

```typescript
// Current:
export type AgentAnalysisType = 'internal' | 'external'

// Extended:
export type AgentAnalysisType = 'internal' | 'external' | 'batch_inference'

export interface AgentAnalysisConfig {
  analysis_type: AgentAnalysisType
  // internal / external fields (unchanged)
  ...
  // batch_inference fields (new):
  model_task_id?: string
  model_name?: string
  dataset_id?: string
  dataset_name?: string
}
```

#### 5.3.2 Parsing

`parseAnalysisConfig()` already reads `[ANALYSIS_CONFIG]...[/ANALYSIS_CONFIG]` blocks — no change needed. JSON inside the block will be parsed, and the new `analysis_type: "batch_inference"` value flows through naturally.

#### 5.3.3 Card Rendering

Add a `batch_inference` branch in the card render:
```tsx
// Header color: teal (distinct from indigo=internal, orange=external)
const headerColor = {
  internal: 'bg-indigo-50 border-indigo-200',
  external: 'bg-orange-50 border-orange-200',
  batch_inference: 'bg-teal-50 border-teal-200',   // ← NEW
}[config.analysis_type]

// Card body for batch_inference:
// Shows: Model name chip + Dataset name chip + "Run Batch Inference" button
// No metric/chart fields (none needed for unlabeled inference)
```

#### 5.3.4 Submit Action

```typescript
// In onSubmit handler:
if (config.analysis_type === 'batch_inference') {
  await startBatchInference(config.model_task_id!, config.dataset_id!)
  // Then navigate/notify user that job has started (same UX as external validation)
}
```

#### 5.3.5 AI Message Format

When AI intends to suggest batch inference, it emits:
```
[ANALYSIS_CONFIG]
{
  "analysis_type": "batch_inference",
  "model_task_id": "task_abc123",
  "model_name": "TCGA-LUAD Classifier v2",
  "dataset_id": "ds_xyz789",
  "dataset_name": "Validation Cohort 2026"
}
[/ANALYSIS_CONFIG]
```

---

## 4.5 Large Dataset Mitigations

Batch inference jobs can span hundreds to tens of thousands of slides. Both backend and frontend must handle this gracefully.

### 4.5.1 Backend — Chunked Processing (specified in §4.2.4)

- `CHUNK_SIZE = 50` slides per write batch
- Peak in-memory size is bounded to 50 `AIResultCreate` objects regardless of dataset size
- Revocation is checked before **every** chunk write — response time ≤ ~50 slides of inference work
- Partial progress is visible in the SSE stream after each chunk (`progress_callback` fires per slide within chunk)

### 4.5.2 Backend — Results Endpoint Pagination

`GET /results/batch-inference/{task_id}/results` is server-paginated:
- Default page size: `limit=100`
- Maximum page size: `limit=500` (enforced server-side — not a suggestion)
- Response always includes `total` count so the frontend can render pagination controls without an extra request
- The endpoint never returns the full result set regardless of client-requested `limit`

### 4.5.3 Frontend — Paginated Results Table

`BatchInferenceResults/index.tsx` implements simple server-driven pagination:

```
State: { page: 0, pageSize: 100 }
On mount / page change: fetch(taskId, { skip: page * pageSize, limit: pageSize })
Display: <prev> Page N of M <next>  +  t('results.batchInference.showingCount', { shown, total })
```

- No virtual scrolling required at pageSize=100 (DOM row count stays manageable)
- Each page fetch is a lightweight network call; no large arrays held in component state
- "Export CSV" delegates to the server-side streaming endpoint (`/export-csv`) — no full dataset loaded into the browser

### 4.5.4 Frontend — Large Dataset Warning

In `BatchInferenceConfig.tsx`, when a dataset is selected:
- If `dataset.slide_count > 2000`, show an info banner
- i18n key: `results.batchInference.largeDatasetWarning` (see §9)
- Informational only — does not block submission

---

## 6. Data Flow

### 6.1 Submit Flow

```
1. User selects dataset (unlabeled filter active by default, adapts by task type)
2. User selects model (filtered to active models matching dataset task_type/data_type)
3. Frontend validates compatibility (shows warning on mismatch before submit)
4. POST /results/batch-inference → { task_id, status: "pending" }
5. UI transitions to progress view
6. SSE stream updates task status → BackgroundTaskProvider propagates
7. On completion → fetch results (GET /results/batch-inference/{task_id}/results)
```

### 6.2 Results Storage

All results use the **existing `AIResult` table** — no schema changes. Each row:
```
wsi_id, task_id, pred, probs, metadata (risk_score, risk_group, pred_mask_path, etc.), user_id, created_at
```
Task-type-specific data is stored in the `metadata` JSON column (same pattern as External Validation).

The `metadata.pred_mask_path` field stores the relative path to the generated mask file (consistent with how External Validation stores it — field name is `pred_mask_path`, not `pred_mask_file`).

---

## 7. Permission Model

| Check | Implementation | Code Reference |
|---|---|---|
| Dataset read access | `_has_external_validation_dataset_access(user, dataset, db)` | `results.py` |
| GPU permission | `check_dataset_gpu_permission(user, dataset_id, db)` | `dependencies.py` |
| Model ownership | `_require_task_access(model_task, user, db)` | `analysis_utils.py` |
| **Model is active** | `trained_model.is_active` — raise 400 if False | **NEW in v2.0** |
| Task visibility | `TrainingTask.user_id == user.id` unless admin | `results.py` |
| Revocation interrupt | `is_permission_revoked(task_id)` checkpoint before bulk_create | `permission_revocation.py` |
| Frontend route guard | `/results` already has `requireGpu` | `App.tsx` |
| Admin rerun | `effective_task_owner_user_id` from source task | mirrors `start_external_validation` |

---

## 8. Segmentation Hard Contract

Segmentation datasets are constrained: `task_type=segmentation`, `data_type=patch`, `aggregation_level=file` (`gateway/utils.py`). The batch inference endpoint respects this:
- Compatibility check rejects model/dataset mismatches
- `ensure_dataset_segmentation_contract` called for segmentation tasks before submission
- Results display for segmentation shows mask status + download link (no image-level label display)
- Segmentation datasets are **not** filtered by `unlabeled_only` (GT masks are irrelevant to inference)

---

## 9. i18n Keys Required

New keys in `en-US.json` / `zh-CN.json` / `zh-HK.json` under `results.batchInference`:

```json
{
  "results": {
    "batchInference": {
      "tabLabel": "Batch Inference",
      "datasetLabel": "Target Dataset",
      "modelLabel": "Model",
      "unlabeledOnly": "Unlabeled datasets only",
      "submitButton": "Run Inference",
      "progressTitle": "Running batch inference...",
      "completedSummary": "{{completed}} slides processed in {{duration}}",
      "skippedCount": "{{count}} slides skipped (no tissue)",
      "exportCsv": "Export CSV",
      "noResults": "No results yet. Submit a job above.",
      "compatibilityError": "Model type {{modelType}} is incompatible with dataset type {{datasetType}}",
      "datasetAccessRevoked": "Dataset access has been revoked. Cannot submit new inference jobs.",
      "modelInactive": "The selected model is not active. Please select an active model.",
      "largeDatasetWarning": "This dataset has {{count}} slides. Inference may take a long time. Results will be paginated.",
      "showingCount": "Showing {{shown}} of {{total}} results",
      "pageOf": "Page {{page}} of {{total}}"
    }
  }
}
```

---

## 10. File Change Summary

### Backend (new/modified files)

| File | Change Type | Description |
|---|---|---|
| `server/gateway/routes/results.py` | Modified | Add `POST /results/batch-inference`, `GET /results/datasets-for-inference`, `GET /results/batch-inference/{task_id}/results`, `GET /results/batch-inference/tasks`, `GET /results/batch-inference/{task_id}/export-csv` |
| `server/gateway/routes/inference_batch.py` | **New** | `_run_batch_inference()` orchestrator + new unlabeled inference handlers |
| `server/gateway/models.py` | Modified | Add `BatchInferenceRequest` Pydantic model |
| `server/gateway/task_queue.py` | Modified | Add `TaskType.BATCH_INFERENCE` to enum |
| `server/gateway/main.py` | Modified | Add `batch_inference` case to `resume_interrupted_tasks()`; guard safety net to skip `BATCH_INFERENCE` tasks |
| `server/gateway/routes/chat_intent_policy.py` | Modified | Add `ConversationMode.BATCH_INFERENCE`; inject model/dataset context; add system prompt extension |

### Frontend (new/modified files)

| File | Change Type | Description |
|---|---|---|
| `src/renderer/src/api/batchInference.ts` | **New** | API client for batch inference |
| `src/renderer/src/components/results/BatchInferencePanel/index.tsx` | **New** | Top-level panel |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceConfig.tsx` | **New** | Config form (dataset + model selectors) |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceProgress.tsx` | **New** | SSE-driven progress view |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/index.tsx` | **New** | Results dispatcher + CSV export button |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/ClassificationResults.tsx` | **New** | Classification table |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SurvivalResults.tsx` | **New** | Survival table |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SegmentationResults.tsx` | **New** | Segmentation table |
| `src/renderer/src/pages/ResultsViewerPage.tsx` | Modified | Add 批量推理 tab |
| `src/renderer/src/components/chat/AnalysisConfigCard.tsx` | Modified | Add `analysis_type: 'batch_inference'`; teal card variant; `startBatchInference()` submit |
| `src/renderer/src/locales/en-US.json` | Modified | Add i18n keys |
| `src/renderer/src/locales/zh-CN.json` | Modified | Add i18n keys |
| `src/renderer/src/locales/zh-HK.json` | Modified | Add i18n keys |

---

## 11. Success Criteria

- [ ] `POST /results/batch-inference` creates a task and returns `task_id`
- [ ] Task progresses through `pending → running → completed/failed` with SSE updates visible in BackgroundTaskProvider
- [ ] Results panel shows correct table columns per task type (classification / survival / segmentation)
- [ ] `GET /results/batch-inference/{task_id}/export-csv` downloads a correct CSV for all three task types
- [ ] `GET /results/batch-inference/tasks` lists user's batch inference jobs
- [ ] Permission checks reject: wrong user's model, inaccessible dataset, guest without GPU grant, inactive model
- [ ] Revocation mid-job causes task to fail gracefully with **no partial DB writes** (bulk_create not called)
- [ ] Admin rerun assigns task to original owner, not admin
- [ ] Unlabeled-only filter: hides labeled datasets for classification/survival; always shows all for segmentation
- [ ] Model/dataset type mismatch shows clear error before and at submission
- [ ] Interrupted batch_inference tasks resume correctly via `resume_interrupted_tasks()`
- [ ] `AnalysisConfigCard` renders teal `batch_inference` card from AI message and triggers `startBatchInference()` on submit
- [ ] `ConversationMode.BATCH_INFERENCE` injects correct model/dataset context into AI system prompt
