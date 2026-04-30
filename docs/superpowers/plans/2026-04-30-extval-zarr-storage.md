# External Validation Zarr Storage Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store all external validation prediction artifacts in task-level Zarr bundles and migrate extval readers away from legacy per-WSI `extval_*` files.

**Architecture:** Reuse `AIResultStore` as the single artifact store for extval tasks. External validation inference writes `result` JSON and array artifacts (`attention`, `attention_raw`, `cam`, `pred_mask`) into `/ai_results_bundles/{extval_task_id}.zarr.zip`; analysis and discovery read via store APIs instead of scanning `/ai_results/{wsi_id}`.

**Tech Stack:** Python, FastAPI route modules, `AIResultStore`, pytest, NumPy/Zarr ZipStore.

---

### File Map

- Modify `pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`: replace extval legacy JSON/NPY writes with `AIResultStore.write_wsi_result`, preserve DB metadata, and avoid result-file rereads for survival post-processing.
- Modify `pathlab/pathlab-client/server/gateway/routes/external_validation_analysis.py`: load extval segmentation/classification/survival results from `AIResultStore`.
- Modify `pathlab/pathlab-client/server/gateway/routes/results.py`: stop discovering completed extval cache by scanning legacy `extval_*_result.json`; use bundled results/DB metadata.
- Add or extend tests under `pathlab/pathlab-client/server/tests/`: focused regressions for storage helper behavior, analysis loader behavior, and legacy-file absence.

### Task 1: Add Store-Based Extval Write Tests

**Files:**
- Test: `pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py`
- Modify later: `pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`

- [ ] **Step 1: Write failing tests for the extval result writer helper**

Create tests that call the planned helper with representative payloads:
- patch classification: `result + cam`
- patch segmentation: `result + pred_mask + cam`
- WSI classification/survival: `result + attention + attention_raw`

Assert:
- `/ai_results_bundles/{task_id}.zarr.zip` exists and validates.
- `AIResultStore.read_result(task_id, wsi_id)` returns the same `validation_task_id`, `task_type`, `aggregation_level`, `is_kfold`, `num_folds`, and prediction fields.
- `AIResultStore.read_array(...)` returns the expected array for each artifact.
- No `uploads/ai_results/{wsi_id}/extval_{task_id}_result.json` is written.

- [ ] **Step 2: Run tests to verify they fail**

Run:
`PYTHONPATH=pathlab/pathlab-client/server python -m pytest pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py -q`

Expected: fail because the helper does not exist or still writes legacy files.

- [ ] **Step 3: Implement minimal helper**

Add a small helper in `inference_external_validation.py`:

```python
def _save_extval_ai_result_artifacts(
    uploads_dir: Path,
    task_id: str,
    wsi_id: str,
    result_data: dict[str, Any],
    arrays: dict[str, np.ndarray[Any, Any]] | None = None,
) -> None:
    AIResultStore(uploads_dir).write_wsi_result(
        task_id=task_id,
        wsi_id=wsi_id,
        result=result_data,
        arrays=arrays,
    )
```

- [ ] **Step 4: Run tests to verify helper passes**

Run the same pytest command. Expected: helper tests pass.

### Task 2: Replace Extval Legacy Writes

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`
- Test: `pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py`

- [ ] **Step 1: Add failing tests for no legacy writes in representative save blocks**

Use small direct unit tests around extracted save helper functions if feasible. If full inference setup is too heavy, test helper contracts and static behavior with `rg` assertions that extval writer code no longer contains `json.dump(result_data` to `extval_{task_id}_result.json` or `np.save` for extval prediction artifacts.

- [ ] **Step 2: Run tests and confirm failure**

Expected: tests fail because current code writes legacy JSON/NPY paths.

- [ ] **Step 3: Patch patch-segmentation external validation**

Replace:
- `np.save(...pred_mask.npy)`
- `np.save(...cam.npy)`
- `json.dump(result_data, result_file)`

with:
- `arrays={PRED_MASK_ARTIFACT: pred_mask, CAM_ARTIFACT: cam_map}`
- `_save_extval_ai_result_artifacts(uploads_dir, task_id, wsi_id, result_data, arrays)`

Update `all_results` and DB metadata so `result_file`, `pred_mask_file`, `pred_mask_path`, and `cam_file` are not legacy paths. Keep fields in `result_data` only as logical presence/shape metadata where needed.

- [ ] **Step 4: Patch patch-classification external validation**

Replace CAM `.npy` and result JSON writes with `_save_extval_ai_result_artifacts(... arrays={CAM_ARTIFACT: cam_map})`. Keep `cam_size`, `is_kfold`, `num_folds`, `validation_task_id`, `validation_source` in `result_data`.

- [ ] **Step 5: Patch WSI classification/survival external validation**

Replace `attention_raw`, `attention`, and result JSON writes with store writes. Preserve `aggregation_level`, `case_id`, `is_kfold`, `num_folds`, and survival fields. For preview cache calls that require file paths, skip them for extval bundled arrays unless there is already a store-based preview path.

- [ ] **Step 6: Remove survival JSON post-write mutation**

Refactor survival risk-group enrichment so `median_risk_score` and `risk_group` are included before or during bundle writes. Avoid reopening per-WSI JSON files.

- [ ] **Step 7: Run focused tests**

Run:
`PYTHONPATH=pathlab/pathlab-client/server python -m pytest pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py -q`

Expected: pass.

### Task 3: Migrate Extval Analysis Readers

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/routes/external_validation_analysis.py`
- Test: `pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py`

- [ ] **Step 1: Write failing analysis-loader tests**

Seed an `AIResultStore` bundle with representative extval results and no legacy files. Test that classification, segmentation, and survival loaders return the same records they previously built from JSON files. Prefer extracting small synchronous loader helpers so tests do not need to run full chart generation.

- [ ] **Step 2: Run tests and confirm failure**

Expected: fail because loaders still scan `uploads/ai_results`.

- [ ] **Step 3: Add shared bundle loader**

Add focused helper in `external_validation_analysis.py`:

```python
def _load_extval_bundle_results(task_id: str) -> list[dict[str, Any]]:
    store = AIResultStore(Config.get_uploads_dir())
    results = []
    for wsi_id in store.list_results(task_id):
        data = store.read_result(task_id, wsi_id)
        if data.get("validation_task_id") == task_id:
            results.append(data)
    return results
```

Use it in segmentation/classification/survival loaders.

- [ ] **Step 4: Run analysis-loader tests**

Expected: pass.

### Task 4: Migrate Extval Discovery/Cache Reads

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/routes/results.py`
- Test: `pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py` or existing results-route tests.

- [ ] **Step 1: Write failing discovery test**

Seed an extval bundle and assert the completed/existing external validation discovery path can identify it without legacy `extval_*_result.json` files.

- [ ] **Step 2: Run test and confirm failure**

Expected: fail because `results.py` still scans legacy files.

- [ ] **Step 3: Replace legacy scan with store lookup**

Use `AIResultStore.list_results(validation_task_id)` and `read_result(...)` to build the same metadata shape. Use `artifact_exists(...)` for `attention`, `cam`, and `pred_mask` instead of deriving sibling paths.

- [ ] **Step 4: Run discovery test**

Expected: pass.

### Task 5: Verification Sweep

**Files:**
- Changed files from prior tasks.

- [ ] **Step 1: Run focused pytest suite**

Run:
`PYTHONPATH=pathlab/pathlab-client/server python -m pytest pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py pathlab/pathlab-client/server/tests/test_ai_result_store.py pathlab/pathlab-client/server/tests/test_storage_ai_result_bundles.py -q`

- [ ] **Step 2: Compile changed Python files**

Run:
`PYTHONPATH=pathlab/pathlab-client/server python -m py_compile pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py pathlab/pathlab-client/server/gateway/routes/external_validation_analysis.py pathlab/pathlab-client/server/gateway/routes/results.py pathlab/pathlab-client/server/tests/test_external_validation_zarr_storage.py`

- [ ] **Step 3: Run LSP diagnostics on changed files**

Check errors for each modified Python file and distinguish pre-existing diagnostics from new ones.

- [ ] **Step 4: Real storage smoke check**

If an extval task can be safely run or an existing extval bundle can be produced in test storage, verify:
- bundle exists at `/ssd/Pathlab_Storage/ai_results_bundles/{extval_task_id}.zarr.zip`
- `validate_bundle` is true
- no new legacy `uploads/ai_results/*/extval_{task_id}_*` files are created

- [ ] **Step 5: Summarize results**

Report exact tests run, remaining risks, and any external validation modes that could not be runtime-smoked locally.
