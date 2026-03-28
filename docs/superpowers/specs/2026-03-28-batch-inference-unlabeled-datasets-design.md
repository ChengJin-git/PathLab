# PathLab Batch Inference on Unlabeled Datasets — Design Spec

**Date**: 2026-03-28  
**Version**: 1.0  
**Status**: Approved for Implementation

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
- Strictly conform to the existing permission model (`check_dataset_access_permission`, `check_dataset_gpu_permission`, `_require_task_access`, revocation checkpoints)

---

## 3. Non-Goals

- Computing accuracy/AUC/metrics (no ground truth available — that is External Validation's job)
- Modifying any existing inference route handlers (`_run_inference_wsi_classification`, etc.)
- A standalone new page/route (entry lives inside the existing `/results` page)

---

## 4. Architecture

### 4.1 System Overview

```
User (Results page → Batch Inference Tab)
    │
    ▼
POST /results/batch-inference
    │  permission checks (dataset access + GPU + model access + compatibility)
    ▼
TrainingTask (task_type="batch_inference") created in DB
    │
    ▼
GPU Task Queue (existing TaskQueue.submit, TaskType.INFERENCE)
    │
    ▼
_run_batch_inference() [new orchestrator in inference_batch.py]
    │  routes to existing handlers:
    ├─ WSI classification   → _run_inference_wsi_classification()
    ├─ Patch classification → _run_inference_patch_classification()
    ├─ Survival             → _run_inference_wsi_survival()
    └─ Segmentation         → _run_inference_patch_segmentation()
         │
         ▼
    AIResult rows written per WSI (same table as all other inference)
    │
    ▼
SSE progress via existing training task stream
    │
    ▼
GET /results/batch-inference/{task_id}/results
    │
    ▼
Frontend BatchInferencePanel — task-type-specific results table
```

### 4.2 Backend Components

#### 4.2.1 New Pydantic Models (`gateway/models.py`)

```python
class BatchInferenceRequest(BaseModel):
    model_id: str
    dataset_id: str
    rerun_from_task_id: Optional[str] = None  # Admin rerun only
```

#### 4.2.2 New Endpoints in `routes/results.py`

**`GET /results/datasets-for-inference`**  
Returns datasets suitable for batch inference (all datasets user can access with GPU permission). Adds `unlabeled_only` query param filter (`distinct_label_count == 0`). Reuses `get_datasets_for_validation` logic but does not exclude external_validation task_type entries. Returns same response schema as `datasets-for-validation`.

**`POST /results/batch-inference`**  
Permission checks (in order, mirroring `start_external_validation`):
1. `_require_task_access(model_task, user, db)` — model ownership
2. `_has_external_validation_dataset_access(user, dataset, db)` — dataset read access
3. `check_dataset_gpu_permission(user, dataset_id, db)` — GPU gate
4. Model/dataset compatibility: `model.task_type` must match `dataset.data_group.task_type`; `model.data_type` must match `dataset.data_group.data_type`
5. Admin rerun: if `user.is_admin() and req.rerun_from_task_id`, preserve original task owner (same as `start_external_validation`)

Creates `TrainingTask` with:
- `task_type = "batch_inference"` (new value, no DB schema change needed — stored as string)
- `status = TaskStatus.PENDING`
- `user_id = effective_task_owner_user_id`
- `source_dataset_id` linked

Submits to task queue as `TaskType.INFERENCE`.

Returns: `{ task_id, status, total_wsi, message }`

**`GET /results/batch-inference/{task_id}/results`**  
Returns per-WSI inference results for a completed batch_inference task:
- Auth: task owner/admin (same as other task endpoints)
- Query: `AIResult JOIN WSISlide WHERE AIResult.task_id = task_id`
- Response schema varies by task_type (classification/survival/segmentation)
- Pagination: `skip` / `limit` params, default limit 1000

#### 4.2.3 New File: `routes/inference_batch.py`

Orchestrator function `_run_batch_inference(task, db, progress_callback, assigned_device)`:

```python
async def _run_batch_inference(task, db, progress_callback, assigned_device):
    """Orchestrate batch inference for an unlabeled dataset."""
    task_type = task.data_group.task_type
    data_type  = task.data_group.data_type

    # Get all WSI IDs from the linked dataset
    wsi_ids = await DatasetRepository.get_wsi_ids(db, source_dataset_id)

    # Permission revocation checkpoint before starting
    if is_permission_revoked(task.task_id):
        raise PermissionRevokedException(task.task_id)

    # Route to existing inference handler
    resources = {"has_model": True, "model_id": model_id, ...}
    if data_type == "patch":
        if task_type in ("segmentation", "patch_segmentation"):
            await _run_inference_patch_segmentation(task, wsi_ids, resources, db,
                                                    progress_callback, assigned_device)
        else:
            await _run_inference_patch_classification(task, wsi_ids, resources, db,
                                                     progress_callback, assigned_device)
    elif task_type in ("survival", "wsi_survival"):
        await _run_inference_wsi_survival(task, wsi_ids, resources, db,
                                         progress_callback, assigned_device)
    else:
        await _run_inference_wsi_classification(task, wsi_ids, resources, db,
                                               progress_callback, assigned_device)
    
    # clear_revocation in finally block
```

Permission revocation checkpoints at same intervals as External Validation:
- Before inference starts
- After each slide's inference completes but before DB write

#### 4.2.4 Task Queue Integration

`start_batch_inference` calls `task_queue.submit(task_id, TaskType.INFERENCE, _run_batch_inference, ...)` — identical pattern to `start_external_validation`.

#### 4.2.5 SSE Progress

No changes needed. The existing training task SSE stream (`GET /tasks/training/stream`) already broadcasts all `TrainingTask` records including the new `batch_inference` type.

---

### 4.3 Frontend Components

#### 4.3.1 New API Client: `api/batchInference.ts`

```typescript
// Types
export interface BatchInferenceTask { task_id, status, total_wsi, dataset_id, model_id, ... }
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
  pred_mask_path?: string | null
  created_at: string | null
}
export interface BatchInferenceResultsResponse {
  items: BatchInferenceResult[]
  total: number
  task_type: string
  data_type: string
}

// Functions
export async function startBatchInference(modelId, datasetId, rerunFromTaskId?): Promise<InferenceTaskResponse>
export async function fetchDatasetsForInference(unlabledOnly?): Promise<{ items: ValidationDataset[], total: number }>
export async function fetchBatchInferenceResults(taskId, options?): Promise<BatchInferenceResultsResponse>
export async function getBatchInferenceTasks(): Promise<{ items: BatchInferenceTask[], total: number }>
export async function exportBatchInferenceCSV(taskId): Promise<void>
```

#### 4.3.2 Component Tree

```
components/results/BatchInferencePanel/
├── index.tsx                          # Top-level panel, manages phase state
├── BatchInferenceConfig.tsx           # Dataset + model selectors, submit button
├── BatchInferenceProgress.tsx         # SSE-driven progress card (reuses BackgroundTaskContext)
└── BatchInferenceResults/
    ├── index.tsx                      # Switches on task_type, shared summary bar
    ├── ClassificationResults.tsx      # Table: filename / pred / prob bars / time
    ├── SurvivalResults.tsx            # Table: filename / risk_score / risk_group badge
    └── SegmentationResults.tsx        # Table: filename / status / mask thumbnail
```

#### 4.3.3 ResultsViewerPage.tsx Changes

Adds a third tab `"batch_inference"` to the existing Tabs component:
```tsx
<TabsTrigger value="batch_inference">批量推理</TabsTrigger>
<TabsContent value="batch_inference">
  <BatchInferencePanel />
</TabsContent>
```

No other changes to existing tab logic.

#### 4.3.4 BackgroundTaskProvider Integration

`BatchInferenceProgress` uses the existing `useBackgroundTasks()` context hook, filtering for `task_type === "batch_inference"` tasks. No new SSE subscriptions needed.

---

## 5. Data Flow

### 5.1 Submit Flow

```
1. User selects dataset (unlabeled filter active by default)
2. User selects model (filtered to compatible task_type/data_type)
3. Frontend validates compatibility client-side (shows warning if mismatch)
4. POST /results/batch-inference → { task_id, status: "pending", total_wsi }
5. UI transitions to progress view
6. SSE stream updates task status → BackgroundTaskProvider propagates
7. On completion → fetch results
```

### 5.2 Results Storage

All results use the **existing `AIResult` table** — no schema changes. Each row:
```
wsi_id, task_id, pred, probs, metadata (risk_score, risk_group, pred_mask_path, etc.), user_id, created_at
```
Task-type-specific data is stored in the `metadata` JSON column (same as External Validation).

---

## 6. Permission Model

| Check | Implementation | Code Reference |
|---|---|---|
| Dataset read access | `_has_external_validation_dataset_access(user, dataset, db)` | `results.py:143` |
| GPU permission | `check_dataset_gpu_permission(user, dataset_id, db)` | `dependencies.py:293` |
| Model ownership | `_require_task_access(model_task, user, db)` | `analysis_utils.py` |
| Task visibility | `TrainingTask.user_id == user.id` unless admin | `results.py:1044` |
| Revocation interrupt | `is_permission_revoked(task_id)` checkpoints | `permission_revocation.py` |
| Frontend route guard | `/results` already has `requireGpu` | `App.tsx:48` |
| Admin rerun | `effective_task_owner_user_id` from source task | mirrored from `results.py:1381` |

---

## 7. Segmentation Hard Contract

Segmentation datasets are constrained: `task_type=segmentation`, `data_type=patch`, `aggregation_level=file` (`gateway/utils.py:41`). The batch inference endpoint respects this:
- Compatibility check rejects model/dataset mismatches
- `ensure_dataset_segmentation_contract` called for segmentation tasks before submission
- Results display for segmentation shows mask status + download link (no image-level label display)

---

## 8. i18n Keys Required

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
      "compatibilityError": "Model task type {{modelType}} is incompatible with dataset type {{datasetType}}",
      "datasetAccessRevoked": "Dataset access has been revoked. Cannot submit new inference jobs."
    }
  }
}
```

---

## 9. File Change Summary

### Backend (new/modified files)

| File | Change Type | Description |
|---|---|---|
| `server/gateway/routes/results.py` | Modified | Add `POST /results/batch-inference`, `GET /results/datasets-for-inference`, `GET /results/batch-inference/{task_id}/results` |
| `server/gateway/routes/inference_batch.py` | New | `_run_batch_inference()` orchestrator |
| `server/gateway/models.py` | Modified | Add `BatchInferenceRequest` Pydantic model |

### Frontend (new/modified files)

| File | Change Type | Description |
|---|---|---|
| `src/renderer/src/api/batchInference.ts` | New | API client for batch inference |
| `src/renderer/src/components/results/BatchInferencePanel/index.tsx` | New | Top-level panel |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceConfig.tsx` | New | Config form |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceProgress.tsx` | New | Progress view |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/index.tsx` | New | Results dispatcher |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/ClassificationResults.tsx` | New | Classification table |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SurvivalResults.tsx` | New | Survival table |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SegmentationResults.tsx` | New | Segmentation table |
| `src/renderer/src/pages/ResultsViewerPage.tsx` | Modified | Add batch inference tab |
| `src/renderer/src/locales/en-US.json` | Modified | Add i18n keys |
| `src/renderer/src/locales/zh-CN.json` | Modified | Add i18n keys |
| `src/renderer/src/locales/zh-HK.json` | Modified | Add i18n keys |

---

## 10. Success Criteria

- [ ] `POST /results/batch-inference` creates a task and returns `task_id`
- [ ] Task progresses through `pending → running → completed/failed` with SSE updates visible in BackgroundTaskProvider
- [ ] Results panel shows correct table columns per task type (classification / survival / segmentation)
- [ ] CSV export downloads correctly for all three task types
- [ ] Permission checks reject: wrong user's model, inaccessible dataset, guest without GPU grant
- [ ] Revocation mid-job causes task to fail gracefully without partial DB writes
- [ ] Admin rerun assigns task to original owner, not admin
- [ ] Unlabeled-only filter correctly hides labeled datasets
- [ ] Model/dataset type mismatch shows clear error before submission
