# Independent Inference Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent inference for user-uploaded unlabeled images using existing active models, with backend task orchestration and manual support from the results/analysis page.

**Architecture:** Reuse the existing batch/external-validation inference pipeline instead of duplicating model execution. Extend the Gateway `results` router with independent-inference endpoints that accept WSI IDs, create `indinfer_*` `TrainingTask` records, enqueue `TaskType.BATCH_INFERENCE` with a narrower WSI list, and expose detailed task/result metadata. Extend the existing frontend batch inference API and the existing third Batch Inference results page tab so it selects active models and uploaded unlabeled images.

**Tech Stack:** Python FastAPI, SQLAlchemy repositories, existing GPU task queue, React 18, TypeScript, React Query, Vitest, pytest.

---

## File Structure

- Modify: `pathlab/pathlab-client/server/gateway/models.py` — add `IndependentInferenceRequest` Pydantic model.
- Modify: `pathlab/pathlab-client/server/gateway/routes/results.py` — add WSI eligibility helpers and endpoints under `/results/independent-inference`.
- Modify: `pathlab/pathlab-client/server/gateway/routes/inference_batch.py` — allow `_run_batch_inference` to accept explicit `wsi_ids` and `execution_mode` for independent inference.
- Modify: `pathlab/pathlab-client/server/backend/database/repositories/training.py` — add list/count helpers for `indinfer_*` task IDs if existing batch helpers are prefix-specific.
- Modify: `pathlab/pathlab-client/server/tests/test_batch_inference.py` — add RED/GREEN route/unit coverage.
- Modify: `pathlab/pathlab-client/src/renderer/src/api/batchInference.ts` — add independent inference types and API functions.
- Modify: `pathlab/pathlab-client/test/unit/api/batchInference.test.ts` — add RED/GREEN API client coverage.
- Create: `pathlab/pathlab-client/src/renderer/src/components/results/IndependentInferencePanel.tsx` — UI for model selection, WSI selection, no-model empty state, submission, task list, and detailed results.
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/ResultsViewerPage.tsx` — reuse the existing third `batch-inference` page mode and render the new panel.

## Task 1: Backend Request Model and Listing Endpoints

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/models.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/results.py`
- Test: `pathlab/pathlab-client/server/tests/test_batch_inference.py`

- [ ] **Step 1: Write failing request model test**

Add tests asserting `IndependentInferenceRequest(model_id="model-1", wsi_ids=["wsi-1"])` is valid and empty `wsi_ids` fails validation.

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest server/tests/test_batch_inference.py -q -k independent`

Expected: import/validation failure because `IndependentInferenceRequest` does not exist.

- [ ] **Step 3: Implement request model**

Add `IndependentInferenceRequest` with `model_id: str`, `wsi_ids: list[str]`, and optional `rerun_from_task_id: str | None = None`; validate `wsi_ids` has at least one item.

- [ ] **Step 4: Write failing list endpoint tests**

Add tests for `get_wsi_for_independent_inference`: no active models returns `models_available=False`; unlabeled WSI entries include `wsi_id`, `original_filename`, `dataset_id`, `dataset_name`, `data_type`, `task_type`, `case_id`, and `created_at`.

- [ ] **Step 5: Run list endpoint tests to verify RED**

Run: `python -m pytest server/tests/test_batch_inference.py -q -k independent`

Expected: endpoint function is missing.

- [ ] **Step 6: Implement list endpoint**

Add `GET /results/independent-inference/wsi` that returns uploaded WSIs with no label/survival/segmentation GT depending on data group task type, filtered by user visibility and GPU access. Include `models_available` based on active trained models.

- [ ] **Step 7: Run backend tests for Task 1**

Run: `python -m pytest server/tests/test_batch_inference.py -q -k independent`

Expected: PASS.

## Task 2: Backend Submission and Result Metadata

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/routes/results.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/inference_batch.py`
- Modify if needed: `pathlab/pathlab-client/server/backend/database/repositories/training.py`
- Test: `pathlab/pathlab-client/server/tests/test_batch_inference.py`

- [ ] **Step 1: Write failing submit tests**

Cover no model (404 or 400 detailed error), inactive model (400), incompatible WSI task/data type (400 with skipped details), and successful enqueue creating `indinfer_*` task with explicit `wsi_ids` in `model_config`.

- [ ] **Step 2: Run submit tests to verify RED**

Run: `python -m pytest server/tests/test_batch_inference.py -q -k independent`

Expected: missing endpoint/submission function.

- [ ] **Step 3: Implement submit endpoint**

Add `POST /results/independent-inference` that loads active model, resolves its training task/data group, validates all requested WSIs are accessible, unlabeled, and compatible, creates a `TrainingTask` with `task_id="indinfer_<uuid>"`, stores detailed `model_config`, and submits `_run_batch_inference(..., wsi_ids=validated_ids, execution_mode="independent_inference")`.

- [ ] **Step 4: Extend batch runner minimally**

Update `_run_batch_inference` to prefer explicit `wsi_ids` over `DatasetRepository.get_wsi_ids(db, dataset_id)` and pass `execution_mode` through to external validation implementations. Preserve existing default behavior for `batch_inference`.

- [ ] **Step 5: Add task/result list compatibility**

Either add independent-specific list/result/summary endpoints or generalize existing batch helpers so `indinfer_*` tasks can be listed and read without changing batch URLs.

- [ ] **Step 6: Run backend tests for Task 2**

Run: `python -m pytest server/tests/test_batch_inference.py -q -k 'batch_inference or independent'`

Expected: existing batch tests still pass and new independent tests pass.

## Task 3: Frontend API Client

**Files:**
- Modify: `pathlab/pathlab-client/src/renderer/src/api/batchInference.ts`
- Test: `pathlab/pathlab-client/test/unit/api/batchInference.test.ts`

- [ ] **Step 1: Write failing API tests**

Add tests for `fetchWSIForIndependentInference()`, `startIndependentInference()`, `listIndependentInferenceTasks()`, and `getIndependentInferenceResults()` URLs, request bodies, and error behavior.

- [ ] **Step 2: Run API tests to verify RED**

Run: `npm run test:run -- test/unit/api/batchInference.test.ts`

Expected: missing exports fail.

- [ ] **Step 3: Implement API functions and types**

Add `IndependentInferenceWSI`, `StartIndependentInferenceRequest`, `IndependentInferenceTask`, and wrapper functions using `apiFetch` with `/results/independent-inference...` URLs.

- [ ] **Step 4: Run API tests to verify GREEN**

Run: `npm run test:run -- test/unit/api/batchInference.test.ts`

Expected: PASS.

## Task 4: Frontend Panel and Existing Results Page Mode

**Files:**
- Create: `pathlab/pathlab-client/src/renderer/src/components/results/IndependentInferencePanel.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/ResultsViewerPage.tsx`

- [ ] **Step 1: Add minimal component behavior test if local patterns allow**

Prefer adding a component test for no-model empty state and submit button enablement. If local component test setup is too costly, rely on API tests plus TypeScript/build verification.

- [ ] **Step 2: Implement panel**

Use the `BatchInferencePanel.tsx` structure: model dropdown, WSI selector/table, submit button with `useAsyncAction`, `EmptyStatePanel` for no active models and no eligible images, task list, paginated results table, and CSV export if backend exposes it.

- [ ] **Step 3: Add page mode**

Reuse the existing `batch-inference` PageMode in `ResultsViewerPage.tsx`, keep the segmented-control label as Batch Inference, enable trained models query for that mode, and render `<IndependentInferencePanel trainedModels={trainedModels} />`.

- [ ] **Step 4: Run frontend targeted tests**

Run: `npm run test:run -- test/unit/api/batchInference.test.ts`

Expected: PASS.

## Task 5: Verification

**Files:**
- All modified files.

- [ ] **Step 1: LSP diagnostics**

Run diagnostics on modified Python/TypeScript files. Expected: no errors.

- [ ] **Step 2: Backend focused tests**

Run: `python -m pytest server/tests/test_batch_inference.py -q`

Expected: PASS.

- [ ] **Step 3: Frontend focused tests**

Run: `npm run test:run -- test/unit/api/batchInference.test.ts`

Expected: PASS.

- [ ] **Step 4: Type/build smoke**

Run a relevant TypeScript/build command available in `package.json` or `npx tsc --noEmit` if no dedicated script exists. Expected: no new type errors from modified files.

- [ ] **Step 5: Final review**

Confirm no `as any`, `@ts-ignore`, empty catches, or unrelated edits were introduced. Do not commit unless explicitly requested by the user.
