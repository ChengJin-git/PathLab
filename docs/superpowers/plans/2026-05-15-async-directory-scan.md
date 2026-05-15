# Async Directory Scan Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move batch directory scanning out of the initial HTTP request so huge patch directories do not hit nginx 504 timeouts.

**Architecture:** Reuse the existing storage task table and progress endpoints. Add a scan-directory task endpoint that starts a background scan, stores a generated `scan_id` in task results, and lets the existing paginated `/storage/scan-directory` endpoint serve completed sessions.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, existing `StorageTaskRepository`, React/TypeScript storage settings UI.

---

### Task 1: Backend Async Scan Task

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/models.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/storage_scan.py`
- Test: `pathlab/pathlab-client/server/tests/test_storage_async_scan_task.py`

- [ ] Write failing backend tests for starting a scan task and completing it with a `scan_id` in task results.
- [ ] Run the focused pytest command and confirm the test fails because the endpoint/model does not exist.
- [ ] Add request/response models for starting scan tasks.
- [ ] Add `POST /storage/tasks/scan-directory` in `storage_scan.py` using `BackgroundTasks` and `StorageTaskRepository`.
- [ ] Implement the background worker to reuse `_scan_directory_for_wsi`, create a scan session, update task progress/status/results, and record failures.
- [ ] Run focused pytest and confirm it passes.

### Task 2: Frontend Batch Scan Flow

**Files:**
- Modify: `pathlab/pathlab-client/src/renderer/src/api/storage.ts`
- Modify: `pathlab/pathlab-client/src/renderer/src/components/settings/StorageTab.tsx`

- [ ] Add TypeScript API wrapper for `startScanDirectoryTask` and result typing.
- [ ] Update initial batch scan to start a scan task instead of calling `/scan-directory` directly.
- [ ] Poll existing `getStorageTask` until `completed`/`failed`/`cancelled`, then load page 1 through existing `scanDirectory(scanId=...)`.
- [ ] Preserve existing pagination behavior and segmentation refresh behavior.
- [ ] Keep error messages user-facing and do not introduce unrelated UI changes.

### Task 3: Verification

**Files:**
- Verify changed backend and frontend files.

- [ ] Run LSP diagnostics on all changed source files.
- [ ] Run focused backend pytest for async scan task and existing storage task taxonomy/guard tests.
- [ ] Run the closest frontend typecheck/build command available in `package.json`.
- [ ] Inspect git diff for scope creep.
