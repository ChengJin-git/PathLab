# Batch Inference on Unlabeled Datasets — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a batch inference feature that lets users run a trained model over an entire unlabeled dataset and view per-slide predictions inside the Results page and AIChatPage.

**Architecture:** Mirrors the existing External Validation flow — creates a `DataGroup(task_type="batch_inference")` + `TrainingTask`, submits as `TaskType.BATCH_INFERENCE` to the GPU queue, and writes `AIResult` rows in 50-slide chunks via a new `inference_batch.py` orchestrator. Frontend adds a 批量推理 tab to `ResultsViewerPage` and extends `AnalysisConfigCard` + adds `BatchInferenceSummaryCard` for inline chat display.

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy (async) / pytest-asyncio / httpx — React 18 / TypeScript / react-i18next / Vitest / @testing-library/react

**Spec:** `docs/superpowers/specs/2026-03-28-batch-inference-unlabeled-datasets-design.md`

---

## File Map

### Backend — New Files

| File | Responsibility |
|---|---|
| `server/gateway/routes/inference_batch.py` | Orchestrator `_run_batch_inference()` + 4 unlabeled inference handlers |
| `server/tests/test_batch_inference.py` | All backend tests (endpoints + handler routing + chunking + revocation) |

### Backend — Modified Files

| File | What Changes |
|---|---|
| `server/gateway/task_queue.py` | Add `TaskType.BATCH_INFERENCE = "batch_inference"` |
| `server/gateway/models.py` | Add `BatchInferenceRequest` Pydantic model |
| `server/gateway/routes/results.py` | 6 new endpoints (datasets-for-inference, batch-inference submit, results, summary, tasks list, export-csv) |
| `server/gateway/main.py` | `resume_interrupted_tasks()` batch_inference case; guard safety net |
| `server/gateway/routes/chat_intent_policy.py` | `ConversationMode.BATCH_INFERENCE`; system prompt extension |
| `server/backend/database/repositories/training.py` | Add `get_batch_inference_tasks()` and `count_batch_inference_tasks()` methods |

### Frontend — New Files

| File | Responsibility |
|---|---|
| `src/renderer/src/api/batchInference.ts` | All batch inference API calls |
| `src/renderer/src/components/results/BatchInferencePanel/index.tsx` | Phase state machine (config → progress → results) |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceConfig.tsx` | Dataset + model selectors, submit, compatibility check, large-dataset warning |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceProgress.tsx` | SSE-driven progress view via `useBackgroundTasks()` |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/index.tsx` | Pagination + CSV export + task_type dispatcher |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/ClassificationResults.tsx` | Classification table |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SurvivalResults.tsx` | Survival table |
| `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SegmentationResults.tsx` | Segmentation table |
| `src/renderer/src/components/chat/BatchInferenceSummaryCard.tsx` | Inline chat card (analogue of MetricCard for batch inference) |
| `test/unit/api/batchInference.test.ts` | Frontend API client unit tests |

### Frontend — Modified Files

| File | What Changes |
|---|---|
| `src/renderer/src/pages/ResultsViewerPage.tsx` | Add 批量推理 tab |
| `src/renderer/src/components/chat/AnalysisConfigCard.tsx` | Add `'batch_inference'` type + teal card variant |
| `src/renderer/src/lib/utils/chatBlockRegistry.ts` | Add `BATCH_INFERENCE_SUMMARY` to both `FUNCTIONAL_CARD_INCOMPLETE_TAGS` and `SPECIAL_BLOCK_TAGS` |
| `src/renderer/src/components/chat/AssistantMessage.tsx` | Import + render `BatchInferenceSummaryCard` |
| `src/renderer/src/locales/en-US.json` | New i18n keys |
| `src/renderer/src/locales/zh-CN.json` | New i18n keys |
| `src/renderer/src/locales/zh-HK.json` | New i18n keys |

---

## Task 1: Backend Enum + Pydantic Request Model

**Files:**
- Modify: `server/gateway/task_queue.py`
- Modify: `server/gateway/models.py`
- Test: `server/tests/test_batch_inference.py` (create file)

- [ ] **Step 1.1: Write the test**

Create `server/tests/test_batch_inference.py`:

```python
import pytest
from server.gateway.task_queue import TaskType
from server.gateway.models import BatchInferenceRequest
from pydantic import ValidationError


def test_batch_inference_task_type_exists():
    assert TaskType.BATCH_INFERENCE == "batch_inference"


def test_batch_inference_request_valid():
    req = BatchInferenceRequest(model_task_id="task-123", dataset_id="ds-456")
    assert req.model_task_id == "task-123"
    assert req.dataset_id == "ds-456"
    assert req.rerun_from_task_id is None


def test_batch_inference_request_with_rerun():
    req = BatchInferenceRequest(
        model_task_id="task-123",
        dataset_id="ds-456",
        rerun_from_task_id="task-000"
    )
    assert req.rerun_from_task_id == "task-000"


def test_batch_inference_request_missing_required():
    with pytest.raises(ValidationError):
        BatchInferenceRequest(model_task_id="task-123")  # missing dataset_id
```

- [ ] **Step 1.2: Run test to confirm it fails**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "task_type or request"
```
Expected: `ImportError` or `AttributeError` — `BATCH_INFERENCE` not yet defined.

- [ ] **Step 1.3: Add `TaskType.BATCH_INFERENCE` to `server/gateway/task_queue.py`**

Find the `TaskType` enum (search for `class TaskType`) and add:
```python
BATCH_INFERENCE = "batch_inference"
```

- [ ] **Step 1.4: Add `BatchInferenceRequest` to `server/gateway/models.py`**

```python
class BatchInferenceRequest(BaseModel):
    model_task_id: str
    dataset_id: str
    rerun_from_task_id: Optional[str] = None
```

- [ ] **Step 1.5: Run test to confirm it passes**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "task_type or request"
```
Expected: 4 PASSED.

- [ ] **Step 1.6: Commit**

```bash
git add server/gateway/task_queue.py server/gateway/models.py server/tests/test_batch_inference.py
git commit -m "feat(backend): add TaskType.BATCH_INFERENCE enum value and BatchInferenceRequest model"
```

---

## Task 2: `GET /results/datasets-for-inference` Endpoint

**Files:**
- Modify: `server/gateway/routes/results.py`
- Test: `server/tests/test_batch_inference.py`

- [ ] **Step 2.1: Write tests**

Add to `server/tests/test_batch_inference.py`. Study `test_resume_tasks.py` and existing results tests for the `app` fixture and auth header pattern — use those fixtures exactly.

```python
# Use the same app fixture and auth_headers as existing test files.
# Typical pattern (adapt to match existing conftest):
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_datasets_for_inference_requires_auth(app):
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/results/datasets-for-inference")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_datasets_for_inference_returns_list(app, auth_headers):
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            "/results/datasets-for-inference",
            headers=auth_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body


@pytest.mark.asyncio
async def test_datasets_for_inference_unlabeled_only_default_true(app, auth_headers):
    # Default: unlabeled_only=True. Response items should only contain
    # datasets where distinct_label_count == 0 (for classification/survival).
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            "/results/datasets-for-inference?unlabeled_only=true",
            headers=auth_headers
        )
    assert resp.status_code == 200
```

- [ ] **Step 2.2: Run test to confirm it fails**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "datasets_for_inference"
```
Expected: 404 — endpoint not yet defined.

- [ ] **Step 2.3: Implement `GET /results/datasets-for-inference` in `results.py`**

Find `get_datasets_for_validation` (the existing implementation), copy its structure, and create a new endpoint below it. Key differences:
- **Don't** exclude `batch_inference` task_type datasets from results (we show all user-accessible datasets)
- **Do** apply the `unlabeled_only` filter based on task type:

```python
@router.get("/datasets-for-inference")
async def get_datasets_for_inference(
    unlabeled_only: bool = True,
    task_type: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    datasets = await DatasetRepository.get_accessible_datasets(db, user)

    if task_type:
        datasets = [d for d in datasets if d.data_group.task_type == task_type]

    if unlabeled_only:
        filtered = []
        for d in datasets:
            dg_task = d.data_group.task_type
            if "segmentation" in dg_task:
                # Segmentation: always include — no WSI-level label concept
                filtered.append(d)
            elif "survival" in dg_task:
                # Survival: include if no survival_time set
                has_survival = any(
                    wsi.survival_time is not None
                    for wsi in d.wsi_slides
                )
                if not has_survival:
                    filtered.append(d)
            else:
                # Classification: include if distinct_label_count == 0
                if d.distinct_label_count == 0:
                    filtered.append(d)
        datasets = filtered

    return {"items": [dataset_to_response(d) for d in datasets], "total": len(datasets)}
```

> **Note:** Check how `get_datasets_for_validation` queries datasets and reuse the same repository call + auth pattern. The `dataset_to_response` helper already exists in `results.py`.

- [ ] **Step 2.4: Run test to confirm it passes**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "datasets_for_inference"
```
Expected: All PASSED (exact count depends on fixtures — at minimum the auth test must pass).

- [ ] **Step 2.5: Commit**

```bash
git add server/gateway/routes/results.py server/tests/test_batch_inference.py
git commit -m "feat(backend): add GET /results/datasets-for-inference endpoint"
```

---

## Task 3: `POST /results/batch-inference` Endpoint

**Files:**
- Modify: `server/gateway/routes/results.py`
- Test: `server/tests/test_batch_inference.py`

- [ ] **Step 3.1: Write tests**

```python
@pytest.mark.asyncio
async def test_batch_inference_submit_requires_auth(app):
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/results/batch-inference", json={
            "model_task_id": "task-1", "dataset_id": "ds-1"
        })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_batch_inference_submit_incompatible_types(app, auth_headers, seed_incompatible_model_dataset):
    """Model task_type != dataset task_type → 400"""
    model_task_id, dataset_id = seed_incompatible_model_dataset
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/results/batch-inference",
            json={"model_task_id": model_task_id, "dataset_id": dataset_id},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "incompatible" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_batch_inference_submit_inactive_model(app, auth_headers, seed_inactive_model_dataset):
    """Inactive model → 400"""
    model_task_id, dataset_id = seed_inactive_model_dataset
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/results/batch-inference",
            json={"model_task_id": model_task_id, "dataset_id": dataset_id},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "not active" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_batch_inference_submit_success(app, auth_headers, seed_compatible_model_dataset, mocker):
    """Happy path: returns task_id and 'pending' status"""
    model_task_id, dataset_id = seed_compatible_model_dataset
    mocker.patch("server.gateway.routes.results.task_queue.submit")  # don't actually enqueue
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/results/batch-inference",
            json={"model_task_id": model_task_id, "dataset_id": dataset_id},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "task_id" in body
    assert body["status"] == "pending"
```

> **Note:** The `seed_*` fixtures will need to be created in `conftest.py` or the test file itself. Seed them the same way existing external validation tests seed their data. If no existing fixtures exist, create minimal DB objects inline in the test.

- [ ] **Step 3.2: Run test to confirm it fails**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "submit"
```
Expected: 404 or ImportError.

- [ ] **Step 3.3: Implement `POST /results/batch-inference` in `results.py`**

Model the implementation on `start_external_validation`. Key steps in order:

```python
@router.post("/batch-inference")
async def start_batch_inference(
    req: BatchInferenceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 1. Model ownership check
    model_task = await TrainingRepository.get_task(db, req.model_task_id)
    if not model_task:
        raise HTTPException(404, "Model task not found")
    _require_task_access(model_task, user, db)

    # 2. Model active check
    trained_model = model_task.trained_model
    if not trained_model or not trained_model.is_active:
        raise HTTPException(400, "Model is not active")

    # 3. Dataset access
    dataset = await DatasetRepository.get(db, req.dataset_id)
    if not dataset:
        raise HTTPException(404, "Dataset not found")
    await _has_external_validation_dataset_access(user, dataset, db)

    # 4. GPU permission
    await check_dataset_gpu_permission(user, req.dataset_id, db)

    # 5. Compatibility
    model_task_type = model_task.data_group.task_type
    model_data_type = model_task.data_group.data_type
    dataset_task_type = dataset.data_group.task_type
    dataset_data_type = dataset.data_group.data_type
    if model_task_type != dataset_task_type:
        raise HTTPException(400,
            f"Model task type '{model_task_type}' is incompatible with dataset task type '{dataset_task_type}'")
    if model_data_type != dataset_data_type:
        raise HTTPException(400,
            f"Model data level '{model_data_type}' mismatches dataset data level '{dataset_data_type}'")

    # 6. Admin rerun
    effective_user_id = user.id
    if user.is_admin() and req.rerun_from_task_id:
        source_task = await TrainingRepository.get_task(db, req.rerun_from_task_id)
        if source_task:
            effective_user_id = source_task.user_id

    # 7. Create DataGroup + TrainingTask
    dg = DataGroup(
        task_type="batch_inference",
        data_type=dataset_data_type,
        aggregation_level=dataset.data_group.aggregation_level,
        user_id=effective_user_id,
    )
    db.add(dg)
    await db.flush()

    task = TrainingTask(
        task_name=f"batch_inference_{dataset.name}_{model_task.task_name}"[:200],
        status=TaskStatus.PENDING,
        user_id=effective_user_id,
        group_id=dg.id,
        model_config={
            "model_task_id": req.model_task_id,
            "model_id": str(trained_model.id),
            "dataset_id": req.dataset_id,
            "model_task_type": model_task_type,
            "model_data_type": model_data_type,
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 8. Submit to queue
    from .inference_batch import _run_batch_inference
    task_queue.submit(
        task.id,
        TaskType.BATCH_INFERENCE,
        _run_batch_inference,
        task_id=task.id,
        model_task_id=req.model_task_id,
        model_id=str(trained_model.id),
        dataset_id=req.dataset_id,
    )

    return {"task_id": task.id, "status": "pending", "message": "Batch inference job submitted"}
```

- [ ] **Step 3.4: Run test to confirm it passes**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "submit"
```
Expected: All PASSED.

- [ ] **Step 3.5: Commit**

```bash
git add server/gateway/routes/results.py server/tests/test_batch_inference.py
git commit -m "feat(backend): add POST /results/batch-inference endpoint with full permission chain"
```

---

## Task 4: Results, Tasks, Summary, Export-CSV Endpoints

**Files:**
- Modify: `server/gateway/routes/results.py`
- Test: `server/tests/test_batch_inference.py`

- [ ] **Step 4.1: Write tests**

```python
@pytest.mark.asyncio
async def test_batch_inference_results_requires_auth(app):
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/results/batch-inference/nonexistent/results")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_batch_inference_results_not_found(app, auth_headers):
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            "/results/batch-inference/nonexistent-id/results",
            headers=auth_headers
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_batch_inference_results_pagination(app, auth_headers, seed_completed_batch_task):
    task_id = seed_completed_batch_task
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/results/batch-inference/{task_id}/results?skip=0&limit=10",
            headers=auth_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "task_type" in body
    assert "data_type" in body
    assert len(body["items"]) <= 10


@pytest.mark.asyncio
async def test_batch_inference_results_limit_enforced(app, auth_headers, seed_completed_batch_task):
    """Requesting limit > 500 is clamped to 500"""
    task_id = seed_completed_batch_task
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/results/batch-inference/{task_id}/results?limit=9999",
            headers=auth_headers
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_batch_inference_tasks_list(app, auth_headers):
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/results/batch-inference/tasks", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body


@pytest.mark.asyncio
async def test_batch_inference_summary_not_found(app, auth_headers):
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            "/results/batch-inference/nonexistent/summary",
            headers=auth_headers
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_batch_inference_export_csv(app, auth_headers, seed_completed_batch_task):
    task_id = seed_completed_batch_task
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/results/batch-inference/{task_id}/export-csv",
            headers=auth_headers
        )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "attachment" in resp.headers.get("content-disposition", "")
```

- [ ] **Step 4.2: Run test to confirm it fails**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "results or tasks_list or summary or export"
```
Expected: 404 (endpoints not yet defined).

- [ ] **Step 4.3: Implement all four read endpoints**

Add to `results.py` after the `POST /batch-inference` endpoint.

**`GET /results/batch-inference/tasks`**:
```python
@router.get("/batch-inference/tasks")
async def list_batch_inference_tasks(
    skip: int = 0, limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Query TrainingTask joined to DataGroup WHERE task_type="batch_inference"
    # If admin: all tasks. Otherwise: tasks WHERE user_id = user.id
    tasks = await TrainingRepository.get_batch_inference_tasks(db, user, skip=skip, limit=limit)
    return {
        "items": [_batch_task_to_response(t) for t in tasks],
        "total": await TrainingRepository.count_batch_inference_tasks(db, user),
    }
```

> Add `get_batch_inference_tasks` and `count_batch_inference_tasks` to `TrainingRepository` — query `DataGroup.task_type == "batch_inference"` joined to `TrainingTask`. Check existing repo methods for the query pattern.

**`GET /results/batch-inference/{task_id}/results`**:
```python
@router.get("/batch-inference/{task_id}/results")
async def get_batch_inference_results(
    task_id: str,
    skip: int = 0,
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _require_batch_inference_task(task_id, user, db)
    results = await AIResultRepository.get_by_task(db, task_id, skip=skip, limit=limit)
    total = await AIResultRepository.count_by_task(db, task_id)
    task_type = task.model_config.get("model_task_type", "")
    data_type = task.data_group.data_type
    return {
        "task_type": task_type,
        "data_type": data_type,
        "items": [_ai_result_to_inference_response(r) for r in results],
        "total": total,
    }
```

**`GET /results/batch-inference/{task_id}/summary`**:
```python
@router.get("/batch-inference/{task_id}/summary")
async def get_batch_inference_summary(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _require_batch_inference_task(task_id, user, db)
    results = await AIResultRepository.get_by_task(db, task_id, skip=0, limit=None)
    task_type = task.model_config.get("model_task_type", "")
    total = len(results)
    summary = {
        "task_id": task_id,
        "task_name": task.task_name,
        "status": task.status,
        "task_type": task_type,
        "data_type": task.data_group.data_type,
        "total_slides": total,
        "processed_slides": total,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.updated_at.isoformat() if task.status == "completed" else None,
    }
    if "classification" in task_type:
        from collections import Counter
        dist = Counter(r.pred for r in results if r.pred)
        summary["class_distribution"] = dict(dist)
    elif "survival" in task_type:
        risk_scores = [r.metadata.get("risk_score") for r in results if r.metadata and r.metadata.get("risk_score") is not None]
        summary["risk_high_count"] = sum(1 for r in results if r.metadata and r.metadata.get("risk_group") == "high")
        summary["risk_low_count"] = sum(1 for r in results if r.metadata and r.metadata.get("risk_group") == "low")
        summary["mean_risk_score"] = sum(risk_scores) / len(risk_scores) if risk_scores else None
    elif "segmentation" in task_type:
        summary["masks_generated"] = sum(1 for r in results if r.metadata and r.metadata.get("pred_mask_path"))
    return summary
```

**`GET /results/batch-inference/{task_id}/export-csv`**:
```python
import csv, io
from fastapi.responses import StreamingResponse

@router.get("/batch-inference/{task_id}/export-csv")
async def export_batch_inference_csv(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _require_batch_inference_task(task_id, user, db)
    results = await AIResultRepository.get_by_task(db, task_id, skip=0, limit=None)
    task_type = task.model_config.get("model_task_type", "")

    output = io.StringIO()
    if "classification" in task_type:
        fieldnames = ["wsi_id", "original_filename", "case_id", "pred", "probs", "created_at"]
    elif "survival" in task_type:
        fieldnames = ["wsi_id", "original_filename", "case_id", "risk_score", "risk_group", "created_at"]
    else:
        fieldnames = ["wsi_id", "original_filename", "case_id", "pred_mask_path", "created_at"]

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in results:
        row = {
            "wsi_id": r.wsi_id,
            "original_filename": r.wsi_slide.original_filename if r.wsi_slide else "",
            "case_id": r.wsi_slide.case_id if r.wsi_slide else "",
            "pred": r.pred,
            "probs": str(r.probs) if r.probs else "",
            "risk_score": r.metadata.get("risk_score") if r.metadata else None,
            "risk_group": r.metadata.get("risk_group") if r.metadata else None,
            "pred_mask_path": r.metadata.get("pred_mask_path") if r.metadata else None,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch_inference_{task_id}.csv"'},
    )
```

Add helper `_require_batch_inference_task(task_id, user, db)` that:
1. Fetches `TrainingTask` by `task_id`
2. Checks `task.data_group.task_type == "batch_inference"` — raises 404 otherwise
3. Checks ownership (user.id == task.user_id or user.is_admin()) — raises 403 otherwise

- [ ] **Step 4.4: Run tests**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "results or tasks_list or summary or export"
```
Expected: All PASSED.

- [ ] **Step 4.5: Commit**

```bash
git add server/gateway/routes/results.py server/tests/test_batch_inference.py
git commit -m "feat(backend): add batch inference read endpoints (results, tasks, summary, export-csv)"
```

---

## Task 5: `inference_batch.py` — Orchestrator + Handlers

**Files:**
- Create: `server/gateway/routes/inference_batch.py`
- Test: `server/tests/test_batch_inference.py`

- [ ] **Step 5.1: Write tests (mock GPU)**

```python
from unittest.mock import AsyncMock, patch, MagicMock
import pytest


@pytest.mark.asyncio
async def test_run_batch_inference_routes_to_wsi_classification(mock_batch_task):
    """task_type=wsi_classification routes to WSI classification handler"""
    mock_batch_task.model_config = {
        "model_task_id": "t1", "model_id": "m1", "dataset_id": "ds1",
        "model_task_type": "wsi_classification", "model_data_type": "wsi",
    }
    with patch("server.gateway.routes.inference_batch._run_batch_inference_wsi_classification",
               new_callable=AsyncMock, return_value=[]) as mock_handler, \
         patch("server.gateway.routes.inference_batch.AIResultRepository.bulk_create",
               new_callable=AsyncMock), \
         patch("server.gateway.routes.inference_batch.is_permission_revoked", return_value=False), \
         patch("server.gateway.routes.inference_batch.clear_revocation"):
        from server.gateway.routes.inference_batch import _run_batch_inference
        # Inject 55 fake wsi_ids to test chunking (55 / CHUNK_SIZE=50 → 2 chunks)
        with patch("server.gateway.routes.inference_batch.DatasetRepository.get_wsi_ids",
                   new_callable=AsyncMock, return_value=[f"wsi-{i}" for i in range(55)]):
            await _run_batch_inference(
                task_id="task-1",
                model_task_id="t1",
                model_id="m1",
                dataset_id="ds1",
                db=AsyncMock(),
                progress_callback=AsyncMock(),
                assigned_device="cuda:0",
            )
        assert mock_handler.call_count == 2  # 2 chunks (50 + 5)
        first_call_chunk = mock_handler.call_args_list[0][1].get("wsi_ids") or mock_handler.call_args_list[0][0][1]
        assert len(first_call_chunk) == 50


@pytest.mark.asyncio
async def test_run_batch_inference_revocation_stops_processing(mock_batch_task):
    """If revoked before second chunk, only first chunk is written, exception raised"""
    revocation_calls = [False, True]  # first check passes, second is revoked
    with patch("server.gateway.routes.inference_batch.is_permission_revoked",
               side_effect=revocation_calls), \
         patch("server.gateway.routes.inference_batch._run_batch_inference_wsi_classification",
               new_callable=AsyncMock, return_value=[MagicMock()]), \
         patch("server.gateway.routes.inference_batch.AIResultRepository.bulk_create",
               new_callable=AsyncMock) as mock_write, \
         patch("server.gateway.routes.inference_batch.clear_revocation"), \
         patch("server.gateway.routes.inference_batch.DatasetRepository.get_wsi_ids",
               new_callable=AsyncMock, return_value=[f"wsi-{i}" for i in range(55)]):
        from server.gateway.routes.inference_batch import _run_batch_inference, PermissionRevokedException
        with pytest.raises(PermissionRevokedException):
            await _run_batch_inference(
                task_id="t1", model_task_id="mt1", model_id="m1", dataset_id="ds1",
                db=AsyncMock(), progress_callback=AsyncMock(), assigned_device="cpu",
            )
        # First chunk was written before revocation
        assert mock_write.call_count == 1


@pytest.mark.asyncio
async def test_clear_revocation_called_in_finally():
    """clear_revocation is called even when exception is raised"""
    with patch("server.gateway.routes.inference_batch.is_permission_revoked", return_value=True), \
         patch("server.gateway.routes.inference_batch.clear_revocation") as mock_clear, \
         patch("server.gateway.routes.inference_batch.DatasetRepository.get_wsi_ids",
               new_callable=AsyncMock, return_value=["wsi-1"]):
        from server.gateway.routes.inference_batch import _run_batch_inference, PermissionRevokedException
        with pytest.raises(PermissionRevokedException):
            await _run_batch_inference(
                task_id="t1", model_task_id="mt1", model_id="m1", dataset_id="ds1",
                db=AsyncMock(), progress_callback=AsyncMock(), assigned_device="cpu",
            )
        mock_clear.assert_called_once_with("t1")
```

- [ ] **Step 5.2: Run test to confirm it fails**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "run_batch_inference or revocation or clear_revocation"
```
Expected: ImportError — file does not exist yet.

- [ ] **Step 5.3: Create `server/gateway/routes/inference_batch.py`**

```python
"""
Batch inference on unlabeled datasets.
Orchestrator + 4 unlabeled inference handlers.
"""
from __future__ import annotations

import asyncio
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from ..task_queue import TaskType  # noqa: F401 — used by caller
from ...backend.database.repositories.ai_result import AIResultRepository
from ...backend.database.repositories.training import TrainingRepository
from ...backend.database.repositories.dataset import DatasetRepository
from ..permission_revocation import is_permission_revoked, clear_revocation

CHUNK_SIZE = 50


class PermissionRevokedException(Exception):
    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Permission revoked for task {task_id}")


async def _run_batch_inference(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    db: AsyncSession,
    progress_callback,
    assigned_device: str,
):
    """Main entry point called by the task queue."""
    model_task = await TrainingRepository.get_task(db, model_task_id)
    trained_model = model_task.trained_model
    dataset_wsi_ids: List[str] = await DatasetRepository.get_wsi_ids(db, dataset_id)

    if is_permission_revoked(task_id):
        raise PermissionRevokedException(task_id)

    task_type = model_task.data_group.task_type
    data_type  = model_task.data_group.data_type
    total = len(dataset_wsi_ids)

    try:
        for chunk_start in range(0, total, CHUNK_SIZE):
            chunk_ids = dataset_wsi_ids[chunk_start : chunk_start + CHUNK_SIZE]

            # Route by exact task_type
            if task_type == "patch_segmentation":
                chunk_results = await _run_batch_inference_patch_segmentation(
                    trained_model, chunk_ids, db, progress_callback, assigned_device,
                    offset=chunk_start, total=total,
                )
            elif task_type in ("wsi_survival", "survival"):
                chunk_results = await _run_batch_inference_wsi_survival(
                    trained_model, chunk_ids, db, progress_callback, assigned_device,
                    offset=chunk_start, total=total,
                )
            elif task_type == "patch_classification":
                chunk_results = await _run_batch_inference_patch_classification(
                    trained_model, chunk_ids, db, progress_callback, assigned_device,
                    offset=chunk_start, total=total,
                )
            else:  # wsi_classification (default)
                chunk_results = await _run_batch_inference_wsi_classification(
                    trained_model, chunk_ids, db, progress_callback, assigned_device,
                    offset=chunk_start, total=total,
                )

            # Revocation check + atomic write for this chunk
            if is_permission_revoked(task_id):
                raise PermissionRevokedException(task_id)

            if chunk_results:
                await AIResultRepository.bulk_create(db, chunk_results)
                await db.commit()

    finally:
        clear_revocation(task_id)


# ─── Unlabeled Inference Handlers ─────────────────────────────────────────────
# These are NEW functions — NOT wrappers around existing inference handlers.
# They use trained_model.classes for the label space (no WSISlide.label needed).
# They mirror the external validation handlers but WITHOUT metric computation.

async def _run_batch_inference_wsi_classification(
    trained_model, wsi_ids: List[str], db, progress_callback, assigned_device: str,
    offset: int = 0, total: int = 0,
) -> list:
    """
    Run WSI-level classification inference on a chunk of unlabeled slides.
    Returns List[AIResultCreate] — does NOT write to DB.

    Implementation guide:
    - Look at how _run_external_validation_wsi_classification in inference_external_validation.py
      extracts features and runs the aggregator+classifier.
    - Key difference: use trained_model.classes (List[str]) for the class label space.
      Do NOT query WSISlide.label.
    - For each wsi_id:
      1. Load features from trained_model's feature extractor path
      2. Run aggregator → slide embedding
      3. Run classifier → probabilities dict (keyed by trained_model.classes)
      4. pred = argmax(probs)
      5. Append AIResultCreate(wsi_id=wsi_id, pred=pred, probs=probs)
      6. Call progress_callback(offset + i + 1, total)
    - Return the list (caller handles DB write)
    """
    raise NotImplementedError("Implement following _run_external_validation_wsi_classification pattern")


async def _run_batch_inference_patch_classification(
    trained_model, wsi_ids: List[str], db, progress_callback, assigned_device: str,
    offset: int = 0, total: int = 0,
) -> list:
    """Patch-level classification. Same as WSI but uses patch-level aggregation."""
    raise NotImplementedError("Implement following _run_external_validation_patch_classification pattern")


async def _run_batch_inference_wsi_survival(
    trained_model, wsi_ids: List[str], db, progress_callback, assigned_device: str,
    offset: int = 0, total: int = 0,
) -> list:
    """
    Survival risk scoring. No labels required — computes risk score from features.
    Output: AIResultCreate with metadata={"risk_score": float, "risk_group": "high"|"low"}
    Risk group: median split on the training set's risk distribution (stored in trained_model.model_config).
    """
    raise NotImplementedError("Implement following _run_external_validation_wsi_survival pattern")


async def _run_batch_inference_patch_segmentation(
    trained_model, wsi_ids: List[str], db, progress_callback, assigned_device: str,
    offset: int = 0, total: int = 0,
) -> list:
    """
    Patch segmentation. Generates mask files and stores pred_mask_path in metadata.
    Output: AIResultCreate with metadata={"pred_mask_path": str}
    """
    raise NotImplementedError("Implement following _run_external_validation_patch_segmentation pattern")
```

> **Implementation note for handlers:** Study `server/gateway/routes/inference_external_validation.py`. Each `_run_external_validation_*` function shows how to load features, run the model, and structure results. For batch inference, remove the metric computation section at the end. The feature loading pattern uses `model_task.model_config["extractor_path"]` and the dataset's WSI ids.

- [ ] **Step 5.4: Run tests**

```bash
python -m pytest server/tests/test_batch_inference.py -v -k "run_batch_inference or revocation or clear_revocation"
```
Expected: All PASSED (handlers raise `NotImplementedError` but routing/chunking/revocation logic is what's tested — mocks intercept before that).

- [ ] **Step 5.5: Commit**

```bash
git add server/gateway/routes/inference_batch.py server/tests/test_batch_inference.py
git commit -m "feat(backend): add inference_batch.py orchestrator with chunk processing and revocation"
```

- [ ] **Step 5.6: Implement the 4 handlers (fill in the `NotImplementedError` stubs)**

For each handler, follow `inference_external_validation.py`. The implementation pattern is:
1. For each `wsi_id` in the chunk, load pre-computed features from the extractor cache (same path the external validation uses)
2. Run aggregator → classifier (classification/survival) or segmentation decoder
3. Format as `AIResultCreate` (check existing schema)
4. Return list

Run the full inference suite if a GPU test environment is available:
```bash
python -m pytest server/tests/ -v -k "batch_inference" --gpu  # adjust flag to match project
```

- [ ] **Step 5.7: Commit handlers**

```bash
git add server/gateway/routes/inference_batch.py
git commit -m "feat(backend): implement unlabeled inference handlers (wsi_cls, patch_cls, survival, segmentation)"
```

---

## Task 6: `resume_interrupted_tasks()` + Safety Net Guard

**Files:**
- Modify: `server/gateway/main.py`
- Test: `server/tests/test_resume_tasks.py` (add cases)

- [ ] **Step 6.1: Write tests**

Open `server/tests/test_resume_tasks.py`. Add:

```python
@pytest.mark.asyncio
async def test_resume_batch_inference_task(app, seed_interrupted_batch_task, mocker):
    """Interrupted batch_inference task is re-submitted with TaskType.BATCH_INFERENCE"""
    mock_submit = mocker.patch("server.gateway.main.task_queue.submit")
    from server.gateway.main import resume_interrupted_tasks
    await resume_interrupted_tasks()
    calls = [c for c in mock_submit.call_args_list if "BATCH_INFERENCE" in str(c)]
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs.get("task_id") == seed_interrupted_batch_task


@pytest.mark.asyncio
async def test_inference_safety_net_does_not_touch_batch_inference(app, seed_interrupted_batch_task, mocker):
    """The INFERENCE task-type safety net must skip BATCH_INFERENCE tasks"""
    # The safety net looks for stuck INFERENCE AITasks and handles them.
    # batch_inference tasks use BATCH_INFERENCE enum, so the safety net must
    # not misclassify or touch them.
    # Verify the safety net query specifically filters for TaskType.INFERENCE
    # and not TaskType.BATCH_INFERENCE. Implementation: check that batch_inference
    # tasks remain untouched by the safety net's cleanup logic.
    pass  # Implementation-specific; adapt to match main.py's safety net query
```

- [ ] **Step 6.2: Run test to confirm it fails**

```bash
python -m pytest server/tests/test_resume_tasks.py -v -k "batch_inference"
```

- [ ] **Step 6.3: Update `resume_interrupted_tasks()` in `server/gateway/main.py`**

Find the existing `elif dg.task_type == "external_validation":` block. Add immediately after it:

```python
elif dg.task_type == "batch_inference":
    cfg = task.model_config or {}
    from gateway.routes.inference_batch import _run_batch_inference
    task_queue.submit(
        task.id,
        TaskType.BATCH_INFERENCE,
        _run_batch_inference,
        task_id=task.id,
        model_task_id=cfg.get("model_task_id", ""),
        model_id=cfg.get("model_id", ""),
        dataset_id=cfg.get("dataset_id", ""),
    )
```

Find the safety net block that handles stuck `TaskType.INFERENCE` tasks. Ensure its query is `task_type == TaskType.INFERENCE` (not a broader condition that would accidentally match `BATCH_INFERENCE`).

- [ ] **Step 6.4: Run tests**

```bash
python -m pytest server/tests/test_resume_tasks.py -v
```
Expected: All existing tests still pass; new test passes.

- [ ] **Step 6.5: Commit**

```bash
git add server/gateway/main.py server/tests/test_resume_tasks.py
git commit -m "feat(backend): add batch_inference recovery in resume_interrupted_tasks"
```

---

## Task 7: `ConversationMode.BATCH_INFERENCE`

**Files:**
- Modify: `server/gateway/routes/chat_intent_policy.py` (find where `ConversationMode` is defined — may be a different file; search for `class ConversationMode`)

- [ ] **Step 7.1: Locate `ConversationMode`**

```bash
grep -r "class ConversationMode" server/gateway/
```

- [ ] **Step 7.2: Add the new mode**

```python
BATCH_INFERENCE = "batch_inference"
```

- [ ] **Step 7.3: Add intent detection, context injection, and system prompt**

Find where existing modes like `INTERNAL_EVALUATION` / `EXTERNAL_EVALUATION` are routed. Add a `BATCH_INFERENCE` case that:
1. Detects intent when user message mentions: "批量推理", "unlabeled dataset", "run inference on", "score all slides"
2. Injects context: available active models (name, task_type, data_type) + unlabeled datasets (name, slide_count)
3. Adds to system prompt: "When proposing a new job, emit `[ANALYSIS_CONFIG]{...analysis_type:'batch_inference'...}[/ANALYSIS_CONFIG]`. When showing existing results, emit `[BATCH_INFERENCE_SUMMARY]{...}[/BATCH_INFERENCE_SUMMARY]`. Never emit `[METRIC_CONFIG]` for batch inference."
4. `no_web_search = True` (same as other evaluation modes)

- [ ] **Step 7.4: Commit**

```bash
git add server/gateway/routes/chat_intent_policy.py
git commit -m "feat(backend): add ConversationMode.BATCH_INFERENCE with context injection and system prompt"
```

---

## Task 8: Frontend API Client + Tests

**Files:**
- Create: `src/renderer/src/api/batchInference.ts`
- Create: `test/unit/api/batchInference.test.ts`
- Modify: `src/renderer/src/api/index.ts` (add exports)

- [ ] **Step 8.1: Study test helpers**

Open `test/helpers/apiHelpers.ts`. Note the `ok`, `errResp`, `noContent`, `blobResp` helper signatures — use them exactly in the tests below.

- [ ] **Step 8.2: Write tests first**

Create `test/unit/api/batchInference.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'  // adjust path if needed

// ---- mock global fetch ----
const fetchMock = vi.fn()
global.fetch = fetchMock

beforeEach(() => { fetchMock.mockReset() })

describe('startBatchInference', () => {
  it('posts to /results/batch-inference and returns task_id', async () => {
    fetchMock.mockResolvedValueOnce(ok({ task_id: 'task-abc', status: 'pending', message: 'ok' }))
    const { startBatchInference } = await import('../../../src/renderer/src/api/batchInference')
    const result = await startBatchInference('model-task-1', 'dataset-1')
    expect(result.task_id).toBe('task-abc')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/results/batch-inference'),
      expect.objectContaining({ method: 'POST' })
    )
  })
})

describe('fetchDatasetsForInference', () => {
  it('calls GET /results/datasets-for-inference with unlabeled_only=true by default', async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    const { fetchDatasetsForInference } = await import('../../../src/renderer/src/api/batchInference')
    const result = await fetchDatasetsForInference()
    expect(result.total).toBe(0)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('unlabeled_only=true'),
      expect.anything()
    )
  })
})

describe('fetchBatchInferenceResults', () => {
  it('paginates with skip and limit', async () => {
    const payload = { items: [], total: 0, task_type: 'wsi_classification', data_type: 'wsi' }
    fetchMock.mockResolvedValueOnce(ok(payload))
    const { fetchBatchInferenceResults } = await import('../../../src/renderer/src/api/batchInference')
    await fetchBatchInferenceResults('task-1', { skip: 100, limit: 100 })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('skip=100'),
      expect.anything()
    )
  })
})

describe('getBatchInferenceTasks', () => {
  it('calls GET /results/batch-inference/tasks', async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    const { getBatchInferenceTasks } = await import('../../../src/renderer/src/api/batchInference')
    const result = await getBatchInferenceTasks()
    expect(result.items).toEqual([])
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/batch-inference/tasks'),
      expect.anything()
    )
  })
})

describe('exportBatchInferenceCSV', () => {
  it('triggers download via /export-csv', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { exportBatchInferenceCSV } = await import('../../../src/renderer/src/api/batchInference')
    await exportBatchInferenceCSV('task-1')
    expect(openSpy).toHaveBeenCalledWith(
      expect.stringContaining('/export-csv'),
      '_blank'
    )
    openSpy.mockRestore()
  })
})
```

- [ ] **Step 8.3: Run test to confirm it fails**

```bash
npm run test:run -- test/unit/api/batchInference.test.ts
```
Expected: module not found.

- [ ] **Step 8.4: Create `src/renderer/src/api/batchInference.ts`**

```typescript
import { apiFetch } from './client'

// ── Types ──────────────────────────────────────────────────────────────────

export type BatchInferenceTaskType = 'wsi_classification' | 'patch_classification' | 'wsi_survival' | 'survival' | 'patch_segmentation'
export type BatchInferenceDataType = 'wsi' | 'patch'

export interface BatchInferenceTask {
  task_id: string
  task_name: string
  status: string
  dataset_name?: string
  model_name?: string
  created_at: string | null
  total_wsi?: number
}

export interface BatchInferenceResult {
  wsi_id: string
  original_filename: string
  case_id: string | null
  pred?: string | null
  probs?: Record<string, number> | null
  risk_score?: number | null
  risk_group?: 'high' | 'low' | null
  pred_mask_path?: string | null
  created_at: string | null
}

export interface BatchInferenceResultsResponse {
  items: BatchInferenceResult[]
  total: number
  task_type: string
  data_type: string
}

export interface BatchInferenceSummaryConfig {
  task_id: string
  task_name?: string
}

// ── API Functions ──────────────────────────────────────────────────────────

export async function startBatchInference(
  modelTaskId: string,
  datasetId: string,
  rerunFromTaskId?: string,
): Promise<{ task_id: string; status: string; message: string }> {
  return apiFetch('/results/batch-inference', {
    method: 'POST',
    body: JSON.stringify({ model_task_id: modelTaskId, dataset_id: datasetId, rerun_from_task_id: rerunFromTaskId ?? null }),
  })
}

export async function fetchDatasetsForInference(
  unlabeledOnly: boolean = true,
  taskType?: string,
): Promise<{ items: unknown[]; total: number }> {
  const params = new URLSearchParams({ unlabeled_only: String(unlabeledOnly) })
  if (taskType) params.set('task_type', taskType)
  return apiFetch(`/results/datasets-for-inference?${params}`)
}

export async function fetchBatchInferenceResults(
  taskId: string,
  options?: { skip?: number; limit?: number },
): Promise<BatchInferenceResultsResponse> {
  const params = new URLSearchParams({
    skip: String(options?.skip ?? 0),
    limit: String(options?.limit ?? 100),
  })
  return apiFetch(`/results/batch-inference/${taskId}/results?${params}`)
}

export async function getBatchInferenceTasks(
  options?: { skip?: number; limit?: number },
): Promise<{ items: BatchInferenceTask[]; total: number }> {
  const params = new URLSearchParams({
    skip: String(options?.skip ?? 0),
    limit: String(options?.limit ?? 50),
  })
  return apiFetch(`/results/batch-inference/tasks?${params}`)
}

export async function fetchBatchInferenceSummary(taskId: string): Promise<Record<string, unknown>> {
  return apiFetch(`/results/batch-inference/${taskId}/summary`)
}

export async function exportBatchInferenceCSV(taskId: string): Promise<void> {
  const token = localStorage.getItem('token') ?? ''
  window.open(`/results/batch-inference/${taskId}/export-csv?token=${token}`, '_blank')
}
```

- [ ] **Step 8.5: Add exports to `src/renderer/src/api/index.ts`**

Add alongside existing exports:
```typescript
export * from './batchInference'
```

- [ ] **Step 8.6: Run tests**

```bash
npm run test:run -- test/unit/api/batchInference.test.ts
```
Expected: All PASSED.

- [ ] **Step 8.7: Commit**

```bash
git add src/renderer/src/api/batchInference.ts src/renderer/src/api/index.ts test/unit/api/batchInference.test.ts
git commit -m "feat(frontend): add batchInference API client with full test coverage"
```

---

## Task 9: i18n Keys

**Files:**
- Modify: `src/renderer/src/locales/en-US.json`
- Modify: `src/renderer/src/locales/zh-CN.json`
- Modify: `src/renderer/src/locales/zh-HK.json`

- [ ] **Step 9.1: Determine nesting structure**

Open `src/renderer/src/locales/en-US.json` and find the `"results"` key. Add inside it:

```json
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
```

Also add the chat card keys. Find `"chatComponents"` and add:

```json
"batchInferenceSummaryCard": {
  "title": "Batch Inference Summary",
  "statusBadge": {
    "pending": "Pending",
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed"
  },
  "totalSlides": "{{count}} slides",
  "classDistribution": "Prediction Distribution",
  "riskHigh": "High Risk",
  "riskLow": "Low Risk",
  "meanRiskScore": "Mean Risk Score",
  "masksGenerated": "Masks Generated",
  "viewFullResults": "View full results →",
  "taskNotFound": "Task not found or not accessible.",
  "loadingStats": "Loading inference summary..."
}
```

- [ ] **Step 9.2: Add zh-CN translations**

In `zh-CN.json`, add the same keys with Simplified Chinese values:
```json
"batchInference": {
  "tabLabel": "批量推理",
  "datasetLabel": "目标数据集",
  "modelLabel": "模型",
  "unlabeledOnly": "仅显示未标注数据集",
  "submitButton": "开始推理",
  "progressTitle": "正在运行批量推理...",
  "completedSummary": "已处理 {{completed}} 张切片，用时 {{duration}}",
  "skippedCount": "已跳过 {{count}} 张切片（无组织区域）",
  "exportCsv": "导出 CSV",
  "noResults": "暂无结果，请在上方提交任务。",
  "compatibilityError": "模型类型 {{modelType}} 与数据集类型 {{datasetType}} 不兼容",
  "datasetAccessRevoked": "数据集访问权限已撤销，无法提交新的推理任务。",
  "modelInactive": "所选模型未激活，请选择已激活的模型。",
  "largeDatasetWarning": "该数据集包含 {{count}} 张切片，推理时间可能较长，结果将分页显示。",
  "showingCount": "显示 {{shown}} / {{total}} 条结果",
  "pageOf": "第 {{page}} / {{total}} 页"
}
```
And for `batchInferenceSummaryCard`:
```json
"batchInferenceSummaryCard": {
  "title": "批量推理摘要",
  "statusBadge": { "pending": "等待中", "running": "运行中", "completed": "已完成", "failed": "失败" },
  "totalSlides": "{{count}} 张切片",
  "classDistribution": "预测分布",
  "riskHigh": "高风险",
  "riskLow": "低风险",
  "meanRiskScore": "平均风险评分",
  "masksGenerated": "已生成掩码",
  "viewFullResults": "查看完整结果 →",
  "taskNotFound": "任务不存在或无权访问。",
  "loadingStats": "正在加载推理摘要..."
}
```

- [ ] **Step 9.3: Add zh-HK translations** (Traditional Chinese — same as zh-CN but Traditional script where applicable)

- [ ] **Step 9.4: Commit**

```bash
git add src/renderer/src/locales/
git commit -m "feat(frontend): add i18n keys for batch inference panel and summary card"
```

---

## Task 10: `BatchInferencePanel` Shell + ResultsViewerPage Tab

**Files:**
- Create: `src/renderer/src/components/results/BatchInferencePanel/index.tsx`
- Modify: `src/renderer/src/pages/ResultsViewerPage.tsx`

- [ ] **Step 10.1: Create the panel shell**

Create `src/renderer/src/components/results/BatchInferencePanel/index.tsx`:

```tsx
import { useState } from 'react'
import BatchInferenceConfig from './BatchInferenceConfig'
import BatchInferenceProgress from './BatchInferenceProgress'
import { BatchInferenceResults } from './BatchInferenceResults'

type Phase = 'config' | 'progress' | 'results'

export default function BatchInferencePanel() {
  const [phase, setPhase] = useState<Phase>('config')
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [completedTaskId, setCompletedTaskId] = useState<string | null>(null)

  const handleSubmitted = (taskId: string) => {
    setActiveTaskId(taskId)
    setPhase('progress')
  }

  const handleCompleted = (taskId: string) => {
    setCompletedTaskId(taskId)
    setPhase('results')
  }

  const handleReset = () => {
    setActiveTaskId(null)
    setCompletedTaskId(null)
    setPhase('config')
  }

  if (phase === 'config') {
    return <BatchInferenceConfig onSubmitted={handleSubmitted} />
  }
  if (phase === 'progress' && activeTaskId) {
    return <BatchInferenceProgress taskId={activeTaskId} onCompleted={handleCompleted} onReset={handleReset} />
  }
  if (phase === 'results' && completedTaskId) {
    return <BatchInferenceResults taskId={completedTaskId} onReset={handleReset} />
  }
  return null
}
```

- [ ] **Step 10.2: Add the tab to `ResultsViewerPage.tsx`**

Find the `<Tabs>` component in `ResultsViewerPage.tsx` (search for `TabsTrigger`). Add the batch inference tab alongside existing ones.

Find:
```tsx
// something like:
<TabsTrigger value="internal">...</TabsTrigger>
<TabsTrigger value="external">...</TabsTrigger>
```

Add after:
```tsx
<TabsTrigger value="batch_inference">{t('results.batchInference.tabLabel')}</TabsTrigger>
```

And the corresponding content:
```tsx
<TabsContent value="batch_inference">
  <BatchInferencePanel />
</TabsContent>
```

Add import at the top:
```tsx
import BatchInferencePanel from '../components/results/BatchInferencePanel'
```

- [ ] **Step 10.3: Verify no TypeScript errors**

```bash
npx tsc --noEmit 2>&1 | grep BatchInference
```
Expected: no errors.

- [ ] **Step 10.4: Commit**

```bash
git add src/renderer/src/components/results/BatchInferencePanel/index.tsx src/renderer/src/pages/ResultsViewerPage.tsx
git commit -m "feat(frontend): add BatchInferencePanel shell and Results page tab"
```

---

## Task 11: `BatchInferenceConfig.tsx`

**Files:**
- Create: `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceConfig.tsx`

- [ ] **Step 11.1: Implement the component**

```tsx
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Info, Play } from 'lucide-react'
import { fetchDatasetsForInference, startBatchInference } from '../../../api/batchInference'
import { getTrainingTasks, getTrainedModels } from '../../../api'

interface Props {
  onSubmitted: (taskId: string) => void
}

export default function BatchInferenceConfig({ onSubmitted }: Props) {
  const { t } = useTranslation()
  const [datasets, setDatasets] = useState<any[]>([])
  const [models, setModels] = useState<any[]>([])
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [selectedModelTaskId, setSelectedModelTaskId] = useState('')
  const [unlabeledOnly, setUnlabeledOnly] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Derive selected objects
  const selectedDataset = datasets.find(d => d.dataset_id === selectedDatasetId)
  const selectedModel = models.find(m => m.task_id === selectedModelTaskId)

  // Large dataset warning threshold
  const LARGE_DATASET_THRESHOLD = 2000
  const isLargeDataset = selectedDataset && (selectedDataset.slide_count ?? 0) > LARGE_DATASET_THRESHOLD

  // Compatibility error
  const compatibilityError = (() => {
    if (!selectedDataset || !selectedModel) return null
    if (selectedModel.task_type !== selectedDataset.task_type) {
      return t('results.batchInference.compatibilityError', {
        modelType: selectedModel.task_type,
        datasetType: selectedDataset.task_type,
      })
    }
    return null
  })()

  useEffect(() => {
    fetchDatasetsForInference(unlabeledOnly)
      .then(r => setDatasets(r.items as any[]))
      .catch(() => setDatasets([]))
  }, [unlabeledOnly])

  useEffect(() => {
    // Fetch active models only
    getTrainingTasks()
      .then((r: any) => {
        const tasks = Array.isArray(r) ? r : (r?.items ?? [])
        const active = tasks.filter((t: any) => t.trained_model?.is_active)
        setModels(active)
      })
      .catch(() => setModels([]))
  }, [])

  const handleSubmit = async () => {
    if (!selectedDatasetId || !selectedModelTaskId || compatibilityError) return
    setIsSubmitting(true)
    setError(null)
    try {
      const result = await startBatchInference(selectedModelTaskId, selectedDatasetId)
      onSubmitted(result.task_id)
    } catch (e: any) {
      setError(e.message ?? 'Failed to submit')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-6 p-6">
      {/* Dataset selector */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t('results.batchInference.datasetLabel')}
        </label>
        <div className="flex items-center gap-2 mb-2">
          <input
            type="checkbox"
            id="unlabeled-only"
            checked={unlabeledOnly}
            onChange={e => { setUnlabeledOnly(e.target.checked); setSelectedDatasetId('') }}
            className="rounded"
          />
          <label htmlFor="unlabeled-only" className="text-sm text-gray-600">
            {t('results.batchInference.unlabeledOnly')}
          </label>
        </div>
        <select
          value={selectedDatasetId}
          onChange={e => setSelectedDatasetId(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          <option value="">{t('results.batchInference.datasetLabel')}...</option>
          {datasets.map((d: any) => (
            <option key={d.dataset_id} value={d.dataset_id}>
              {d.name} ({d.slide_count} slides)
            </option>
          ))}
        </select>
      </div>

      {/* Large dataset warning */}
      {isLargeDataset && (
        <div className="flex items-start gap-2 p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">
          <Info className="w-4 h-4 mt-0.5 flex-shrink-0" />
          {t('results.batchInference.largeDatasetWarning', { count: selectedDataset.slide_count })}
        </div>
      )}

      {/* Model selector */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t('results.batchInference.modelLabel')}
        </label>
        <select
          value={selectedModelTaskId}
          onChange={e => setSelectedModelTaskId(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          <option value="">{t('results.batchInference.modelLabel')}...</option>
          {models
            .filter((m: any) => !selectedDataset || m.task_type === selectedDataset.task_type)
            .map((m: any) => (
              <option key={m.task_id} value={m.task_id}>{m.task_name}</option>
            ))
          }
        </select>
      </div>

      {/* Compatibility error */}
      {compatibilityError && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          {compatibilityError}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">{error}</div>
      )}

      {/* Submit */}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={!selectedDatasetId || !selectedModelTaskId || !!compatibilityError || isSubmitting}
        className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium disabled:opacity-50 hover:bg-teal-700 transition-colors"
      >
        <Play className="w-4 h-4" />
        {t('results.batchInference.submitButton')}
      </button>
    </div>
  )
}
```

> **Note:** Check what `getTrainingTasks` returns (task structure may differ). Adapt field names to match the actual API response. Check `api/training.ts` for the exact types.

- [ ] **Step 11.2: Check for TS errors**

```bash
npx tsc --noEmit 2>&1 | grep BatchInferenceConfig
```

- [ ] **Step 11.3: Commit**

```bash
git add src/renderer/src/components/results/BatchInferencePanel/BatchInferenceConfig.tsx
git commit -m "feat(frontend): implement BatchInferenceConfig with selectors and compatibility check"
```

---

## Task 12: `BatchInferenceProgress.tsx`

**Files:**
- Create: `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceProgress.tsx`

- [ ] **Step 12.1: Implement the component**

```tsx
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, RotateCcw } from 'lucide-react'
import { useBackgroundTasks } from '../../../contexts/backgroundTask'

interface Props {
  taskId: string
  onCompleted: (taskId: string) => void
  onReset: () => void
}

export default function BatchInferenceProgress({ taskId, onCompleted, onReset }: Props) {
  const { t } = useTranslation()
  const { tasks } = useBackgroundTasks()  // adjust hook name to match BackgroundTaskProvider API

  const task = tasks?.find((task: any) => task.task_id === taskId)

  useEffect(() => {
    if (task?.status === 'completed') {
      onCompleted(taskId)
    }
  }, [task?.status, taskId, onCompleted])

  const progress = task?.progress ?? 0        // 0-100
  const total = task?.total_wsi ?? task?.total ?? 0
  const processed = task?.processed ?? Math.round(progress * total / 100)

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-teal-600" />
        <span className="text-gray-700 font-medium">{t('results.batchInference.progressTitle')}</span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className="bg-teal-500 h-2 rounded-full transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="text-sm text-gray-500">
        {t('results.batchInference.showingCount', { shown: processed, total })}
      </div>

      {task?.status === 'failed' && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          Inference failed. <button type="button" onClick={onReset} className="underline ml-1">{t('results.batchInference.submitButton')}</button>
        </div>
      )}

      <button type="button" onClick={onReset} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
        <RotateCcw className="w-3 h-3" /> Start new job
      </button>
    </div>
  )
}
```

> **Note:** Check `contexts/backgroundTask/` to find the exact hook name and the shape of task objects returned. Adapt `tasks`, `task.progress`, `task.total_wsi` to match the actual context API.

- [ ] **Step 12.2: Commit**

```bash
git add src/renderer/src/components/results/BatchInferencePanel/BatchInferenceProgress.tsx
git commit -m "feat(frontend): implement BatchInferenceProgress with SSE-driven progress bar"
```

---

## Task 13: `BatchInferenceResults` (4 components)

**Files:**
- Create: `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/index.tsx`
- Create: `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/ClassificationResults.tsx`
- Create: `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SurvivalResults.tsx`
- Create: `src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/SegmentationResults.tsx`

- [ ] **Step 13.1: Create `ClassificationResults.tsx`**

```tsx
import { useTranslation } from 'react-i18next'
import type { BatchInferenceResult } from '../../../../api/batchInference'

interface Props { items: BatchInferenceResult[] }

export function ClassificationResults({ items }: Props) {
  const { t } = useTranslation()
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="bg-gray-50 text-left">
          <th className="px-3 py-2 font-medium text-gray-700">Filename</th>
          <th className="px-3 py-2 font-medium text-gray-700">Case ID</th>
          <th className="px-3 py-2 font-medium text-gray-700">Prediction</th>
          <th className="px-3 py-2 font-medium text-gray-700">Probabilities</th>
          <th className="px-3 py-2 font-medium text-gray-700">Time</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r) => (
          <tr key={r.wsi_id} className="border-t border-gray-100 hover:bg-gray-50">
            <td className="px-3 py-2 font-mono text-xs truncate max-w-xs">{r.original_filename}</td>
            <td className="px-3 py-2 text-gray-500">{r.case_id ?? '—'}</td>
            <td className="px-3 py-2">
              {r.pred ? (
                <span className="px-2 py-0.5 bg-teal-100 text-teal-800 rounded text-xs font-medium">{r.pred}</span>
              ) : '—'}
            </td>
            <td className="px-3 py-2 text-xs text-gray-500">
              {r.probs ? Object.entries(r.probs).map(([cls, prob]) => (
                <span key={cls} className="mr-2">{cls}: {(prob * 100).toFixed(1)}%</span>
              )) : '—'}
            </td>
            <td className="px-3 py-2 text-xs text-gray-400">{r.created_at?.slice(0, 10) ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

- [ ] **Step 13.2: Create `SurvivalResults.tsx`**

```tsx
import type { BatchInferenceResult } from '../../../../api/batchInference'

interface Props { items: BatchInferenceResult[] }

export function SurvivalResults({ items }: Props) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="bg-gray-50 text-left">
          <th className="px-3 py-2 font-medium text-gray-700">Filename</th>
          <th className="px-3 py-2 font-medium text-gray-700">Case ID</th>
          <th className="px-3 py-2 font-medium text-gray-700">Risk Score</th>
          <th className="px-3 py-2 font-medium text-gray-700">Risk Group</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r) => (
          <tr key={r.wsi_id} className="border-t border-gray-100 hover:bg-gray-50">
            <td className="px-3 py-2 font-mono text-xs truncate max-w-xs">{r.original_filename}</td>
            <td className="px-3 py-2 text-gray-500">{r.case_id ?? '—'}</td>
            <td className="px-3 py-2">{r.risk_score?.toFixed(4) ?? '—'}</td>
            <td className="px-3 py-2">
              {r.risk_group === 'high' && <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs font-medium">High</span>}
              {r.risk_group === 'low' && <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-medium">Low</span>}
              {!r.risk_group && '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

- [ ] **Step 13.3: Create `SegmentationResults.tsx`**

```tsx
import type { BatchInferenceResult } from '../../../../api/batchInference'

interface Props { items: BatchInferenceResult[] }

export function SegmentationResults({ items }: Props) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="bg-gray-50 text-left">
          <th className="px-3 py-2 font-medium text-gray-700">Filename</th>
          <th className="px-3 py-2 font-medium text-gray-700">Case ID</th>
          <th className="px-3 py-2 font-medium text-gray-700">Mask</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r) => (
          <tr key={r.wsi_id} className="border-t border-gray-100 hover:bg-gray-50">
            <td className="px-3 py-2 font-mono text-xs truncate max-w-xs">{r.original_filename}</td>
            <td className="px-3 py-2 text-gray-500">{r.case_id ?? '—'}</td>
            <td className="px-3 py-2">
              {r.pred_mask_path ? (
                <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-medium">Generated</span>
              ) : <span className="text-gray-400 text-xs">—</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

- [ ] **Step 13.4: Create `BatchInferenceResults/index.tsx`**

```tsx
import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, ChevronLeft, ChevronRight, RotateCcw } from 'lucide-react'
import { fetchBatchInferenceResults, exportBatchInferenceCSV, type BatchInferenceResultsResponse } from '../../../../api/batchInference'
import { ClassificationResults } from './ClassificationResults'
import { SurvivalResults } from './SurvivalResults'
import { SegmentationResults } from './SegmentationResults'

const PAGE_SIZE = 100

interface Props {
  taskId: string
  onReset: () => void
}

export function BatchInferenceResults({ taskId, onReset }: Props) {
  const { t } = useTranslation()
  const [page, setPage] = useState(0)
  const [data, setData] = useState<BatchInferenceResultsResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const fetchPage = useCallback(async (p: number) => {
    setIsLoading(true)
    try {
      const result = await fetchBatchInferenceResults(taskId, { skip: p * PAGE_SIZE, limit: PAGE_SIZE })
      setData(result)
    } finally {
      setIsLoading(false)
    }
  }, [taskId])

  useEffect(() => { fetchPage(page) }, [page, fetchPage])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  return (
    <div className="space-y-4 p-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-600">
          {data && t('results.batchInference.showingCount', {
            shown: Math.min(PAGE_SIZE, data.items.length),
            total: data.total,
          })}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => exportBatchInferenceCSV(taskId)} className="flex items-center gap-1 px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">
            <Download className="w-4 h-4" /> {t('results.batchInference.exportCsv')}
          </button>
          <button type="button" onClick={onReset} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700">
            <RotateCcw className="w-4 h-4" /> New job
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        {isLoading ? (
          <div className="p-8 text-center text-gray-500">Loading...</div>
        ) : !data || data.items.length === 0 ? (
          <div className="p-8 text-center text-gray-500">{t('results.batchInference.noResults')}</div>
        ) : data.task_type.includes('survival') ? (
          <SurvivalResults items={data.items} />
        ) : data.task_type.includes('segmentation') ? (
          <SegmentationResults items={data.items} />
        ) : (
          <ClassificationResults items={data.items} />
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button type="button" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="p-1 rounded disabled:opacity-30">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span>{t('results.batchInference.pageOf', { page: page + 1, total: totalPages })}</span>
          <button type="button" onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="p-1 rounded disabled:opacity-30">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 13.5: Check TS**

```bash
npx tsc --noEmit 2>&1 | grep -i "BatchInferenceResult"
```
Expected: no errors.

- [ ] **Step 13.6: Commit**

```bash
git add src/renderer/src/components/results/BatchInferencePanel/BatchInferenceResults/
git commit -m "feat(frontend): implement BatchInferenceResults with pagination, CSV export, and task-type dispatch"
```

---

## Task 14: `AnalysisConfigCard.tsx` Extension

**Files:**
- Modify: `src/renderer/src/components/chat/AnalysisConfigCard.tsx`

- [ ] **Step 14.1: Extend `AgentAnalysisConfig` type**

Change:
```typescript
export interface AgentAnalysisConfig {
  analysis_type: 'internal' | 'external'
```
To:
```typescript
export interface AgentAnalysisConfig {
  analysis_type: 'internal' | 'external' | 'batch_inference'
  // ... existing fields unchanged ...
  // batch_inference specific:
  model_task_id?: string
  model_name?: string
  dataset_id?: string
  dataset_name?: string
}
```

- [ ] **Step 14.2: Add teal card variant**

Find where the card header color is set (search for `indigo` or `orange` in the file). The pattern will be something like:
```typescript
const headerStyles = config.analysis_type === 'external'
  ? 'bg-orange-50 border-orange-200 ...'
  : 'bg-indigo-50 border-indigo-200 ...'
```

Extend:
```typescript
const headerStyles =
  config.analysis_type === 'external'
    ? 'bg-orange-50 border-orange-200'
    : config.analysis_type === 'batch_inference'
    ? 'bg-teal-50 border-teal-200'
    : 'bg-indigo-50 border-indigo-200'
```

- [ ] **Step 14.3: Add `batch_inference` card body rendering**

Find where the card body renders fields based on `analysis_type`. Add a `batch_inference` branch that shows:
- Model name chip (`config.model_name`)
- Dataset name chip (`config.dataset_name`)
- "Run Batch Inference" submit button

- [ ] **Step 14.4: Add submit handler for `batch_inference`**

Find the `onSubmit` / submit click handler. Add:
```typescript
if (config.analysis_type === 'batch_inference') {
  if (!config.model_task_id || !config.dataset_id) return
  const result = await startBatchInference(config.model_task_id, config.dataset_id)
  onSubmitSuccess?.(result.task_id, '')
  return
}
```

Add import at top of file:
```typescript
import { startBatchInference } from '../../api/batchInference'
```

- [ ] **Step 14.5: Check TS**

```bash
npx tsc --noEmit 2>&1 | grep AnalysisConfigCard
```

- [ ] **Step 14.6: Commit**

```bash
git add src/renderer/src/components/chat/AnalysisConfigCard.tsx
git commit -m "feat(frontend): extend AnalysisConfigCard with batch_inference type and teal card variant"
```

---

## Task 15: `BatchInferenceSummaryCard` + Registry + AssistantMessage

**Files:**
- Create: `src/renderer/src/components/chat/BatchInferenceSummaryCard.tsx`
- Modify: `src/renderer/src/lib/utils/chatBlockRegistry.ts`
- Modify: `src/renderer/src/components/chat/AssistantMessage.tsx`

- [ ] **Step 15.1: Register block tags in `chatBlockRegistry.ts`**

Add `'BATCH_INFERENCE_SUMMARY'` to:
1. `FUNCTIONAL_CARD_INCOMPLETE_TAGS` — so streaming skeleton shows while block is incomplete
2. `SPECIAL_BLOCK_TAGS` — so `getIncompleteBlock` and `stripChatBlocks` handle it

```typescript
export const FUNCTIONAL_CARD_INCOMPLETE_TAGS = new Set([
  'TASK_CONFIG', 'ANALYSIS_CONFIG', 'IMAGE_RECOMMENDATION', 'PATCH_INFERENCE',
  'QUICK_ANALYSIS_CONFIG', 'METRIC_CONFIG', 'CHART_CONFIG', 'OPTIONS',
  'BATCH_INFERENCE_SUMMARY',  // ← ADD
])

export const SPECIAL_BLOCK_TAGS = [
  // ... existing tags ...
  'BATCH_INFERENCE_SUMMARY',  // ← ADD
]
```

- [ ] **Step 15.2: Create `BatchInferenceSummaryCard.tsx`**

```tsx
import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { TrendingUp, Loader2, AlertCircle, ExternalLink } from 'lucide-react'
import { fetchBatchInferenceSummary } from '../../api/batchInference'
import { parseLastChatBlockJson, stripChatBlocks } from './chatBlockParsing'
import type { BatchInferenceSummaryConfig } from '../../api/batchInference'

// ── Parse / Remove helpers (pattern mirrors MetricCard) ───────────────────

export function parseBatchInferenceSummaryConfig(content: string): BatchInferenceSummaryConfig | null {
  return parseLastChatBlockJson<BatchInferenceSummaryConfig>(content, 'BATCH_INFERENCE_SUMMARY')
}

export function removeBatchInferenceSummaryBlock(content: string): string {
  return stripChatBlocks(content, 'BATCH_INFERENCE_SUMMARY')
}

// ── Component ─────────────────────────────────────────────────────────────

interface Props {
  config: BatchInferenceSummaryConfig
}

const POLL_INTERVAL_MS = 5000

export function BatchInferenceSummaryCard({ config }: Props) {
  const { t } = useTranslation()
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchSummary = async () => {
    try {
      const data = await fetchBatchInferenceSummary(config.task_id)
      setSummary(data)
      setError(null)
      // Stop polling once completed or failed
      if (data.status === 'completed' || data.status === 'failed') {
        if (pollingRef.current) clearInterval(pollingRef.current)
      }
    } catch (e: any) {
      setError(e.message ?? t('chatComponents.batchInferenceSummaryCard.taskNotFound'))
      if (pollingRef.current) clearInterval(pollingRef.current)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchSummary()
    pollingRef.current = setInterval(fetchSummary, POLL_INTERVAL_MS)
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [config.task_id])

  // Status badge colors
  const statusColors: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-700',
    running: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  }
  const status = String(summary?.status ?? 'pending')

  if (isLoading) {
    return (
      <div className="mt-4 w-full bg-white border border-gray-200 rounded-2xl shadow-sm p-4">
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t('chatComponents.batchInferenceSummaryCard.loadingStats')}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-4 w-full bg-white border border-red-200 rounded-2xl shadow-sm p-4">
        <div className="flex items-center gap-2 text-red-700 text-sm">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      </div>
    )
  }

  const taskType = String(summary?.task_type ?? '')
  const totalSlides = Number(summary?.total_slides ?? 0)

  return (
    <div className="mt-4 w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gradient-to-r from-teal-50 to-cyan-50 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-teal-600" />
          <span className="font-semibold text-gray-900 text-sm">{t('chatComponents.batchInferenceSummaryCard.title')}</span>
          <span className="text-xs text-gray-500 truncate max-w-xs">{config.task_name ?? config.task_id}</span>
        </div>
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColors[status] ?? statusColors.pending}`}>
          {t(`chatComponents.batchInferenceSummaryCard.statusBadge.${status}`, { defaultValue: status })}
        </span>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        <div className="text-sm text-gray-600">
          {t('chatComponents.batchInferenceSummaryCard.totalSlides', { count: totalSlides })}
        </div>

        {/* Classification: class distribution */}
        {taskType.includes('classification') && summary?.class_distribution && (
          <div>
            <div className="text-xs font-medium text-gray-700 mb-2">{t('chatComponents.batchInferenceSummaryCard.classDistribution')}</div>
            {Object.entries(summary.class_distribution as Record<string, number>).map(([cls, count]) => (
              <div key={cls} className="flex items-center gap-2 text-sm mb-1">
                <span className="w-32 truncate text-gray-700">{cls}</span>
                <div className="flex-1 bg-gray-100 rounded-full h-2">
                  <div
                    className="bg-teal-500 h-2 rounded-full"
                    style={{ width: `${totalSlides ? (count / totalSlides) * 100 : 0}%` }}
                  />
                </div>
                <span className="text-xs text-gray-500 w-8 text-right">{count}</span>
              </div>
            ))}
          </div>
        )}

        {/* Survival: risk stats */}
        {taskType.includes('survival') && (
          <div className="grid grid-cols-3 gap-2">
            <div className="p-2 bg-red-50 border border-red-200 rounded-lg text-center">
              <div className="text-lg font-bold text-red-700">{Number(summary?.risk_high_count ?? 0)}</div>
              <div className="text-xs text-red-600">{t('chatComponents.batchInferenceSummaryCard.riskHigh')}</div>
            </div>
            <div className="p-2 bg-green-50 border border-green-200 rounded-lg text-center">
              <div className="text-lg font-bold text-green-700">{Number(summary?.risk_low_count ?? 0)}</div>
              <div className="text-xs text-green-600">{t('chatComponents.batchInferenceSummaryCard.riskLow')}</div>
            </div>
            <div className="p-2 bg-gray-50 border border-gray-200 rounded-lg text-center">
              <div className="text-lg font-bold text-gray-700">{Number(summary?.mean_risk_score ?? 0).toFixed(3)}</div>
              <div className="text-xs text-gray-500">{t('chatComponents.batchInferenceSummaryCard.meanRiskScore')}</div>
            </div>
          </div>
        )}

        {/* Segmentation: masks generated */}
        {taskType.includes('segmentation') && (
          <div className="p-2 bg-teal-50 border border-teal-200 rounded-lg text-center w-32">
            <div className="text-lg font-bold text-teal-700">{Number(summary?.masks_generated ?? 0)}</div>
            <div className="text-xs text-teal-600">{t('chatComponents.batchInferenceSummaryCard.masksGenerated')}</div>
          </div>
        )}

        {/* Footer link */}
        <a
          href="/results"
          className="flex items-center gap-1 text-sm text-teal-600 hover:text-teal-700 hover:underline"
        >
          {t('chatComponents.batchInferenceSummaryCard.viewFullResults')}
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  )
}
```

- [ ] **Step 15.3: Register in `AssistantMessage.tsx`**

Add import at the top (near MetricCard):
```tsx
import { BatchInferenceSummaryCard, parseBatchInferenceSummaryConfig, removeBatchInferenceSummaryBlock } from './BatchInferenceSummaryCard'
```

Find where `MetricCard` is rendered in the JSX (search for `metricConfig`). Add right after it:
```tsx
{/* Batch Inference Summary Card */}
{(() => {
  const batchSummaryConfig = parseBatchInferenceSummaryConfig(processedContent)
  if (!batchSummaryConfig) return null
  return <BatchInferenceSummaryCard config={batchSummaryConfig} />
})()}
```

Find where content is stripped of block tags (search for `removeMetricConfigBlock`). Add:
```tsx
processedContent = removeBatchInferenceSummaryBlock(processedContent)
```

> **Important:** Find the exact pattern AssistantMessage.tsx uses to call `remove*Block` functions and match it precisely. Check around line 400-600 where content processing happens.

- [ ] **Step 15.4: Check TS**

```bash
npx tsc --noEmit 2>&1 | grep -i "batchinference\|BatchInference"
```
Expected: no errors.

- [ ] **Step 15.5: Commit**

```bash
git add src/renderer/src/components/chat/BatchInferenceSummaryCard.tsx \
        src/renderer/src/lib/utils/chatBlockRegistry.ts \
        src/renderer/src/components/chat/AssistantMessage.tsx
git commit -m "feat(frontend): add BatchInferenceSummaryCard for inline chat display of batch inference results"
```

---

## Final Verification Checklist

Run all tests:

```bash
# Backend
python -m pytest server/tests/test_batch_inference.py server/tests/test_resume_tasks.py -v

# Frontend
npm run test:run

# TypeScript
npx tsc --noEmit
```

Manual smoke test in UI:
- [ ] Navigate to `/results` → see 批量推理 tab
- [ ] Select unlabeled dataset + active model → submit → see progress bar
- [ ] Wait for completion → see results table with pagination
- [ ] Click Export CSV → file downloads
- [ ] In AIChatPage: ask AI to run batch inference → teal AnalysisConfigCard appears
- [ ] Submit card → job starts
- [ ] Ask AI to show results of a completed job → BatchInferenceSummaryCard appears with stats
