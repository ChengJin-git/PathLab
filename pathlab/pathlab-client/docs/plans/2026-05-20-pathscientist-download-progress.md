# PathScientist Download Progress Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show live dataset download progress in the PathScientist acquisition card.

**Architecture:** Dataset providers write `.dataset/download_progress.json`; the gateway merges that sidecar into session state and emits `state` SSE events while acquisition is blocked; the frontend reads `state.download_progress` and renders progress in the acquisition disclosure. Kaggle uses a lightweight polling wrapper around the CLI so the sidecar updates during long blocking downloads.

**Tech Stack:** FastAPI gateway, PathScientist dataset providers, React/Vitest PathScientist UI.

---

### Task 1: Gateway sidecar bridge

**Files:**
- Modify: `server/gateway/routes/pathscientist.py`
- Test: `server/tests/test_pathscientist_routes.py`

**Steps:**
1. Write a failing test where a fake runner creates `session_<id>/.dataset/download_progress.json` and emits a progress state; assert emitted state includes `download_progress`.
2. Add helpers to resolve workspace from state and load sidecar JSON safely.
3. Merge sidecar into every runner progress event and final state.
4. Add a short background poller during `_run` so state events continue while the runner is blocked.
5. Run route tests.

### Task 2: Kaggle provider progress

**Files:**
- Modify: `server/backend/pathscientist/dataset/providers/kaggle.py`
- Test: `server/backend/pathscientist/tests/test_dataset_providers.py`

**Steps:**
1. Write a failing test that calls `KaggleProvider.download(..., progress=reporter)` and asserts the progress sidecar is written.
2. Update `download` to accept optional `progress`.
3. For the default CLI path, use `Popen` and poll target file sizes while waiting; for injected test runners, keep backward-compatible runner behavior and write start/finish progress.
4. Run provider tests.

### Task 3: Frontend rendering

**Files:**
- Modify: `src/renderer/src/lib/pathscientistEventSelectors.ts`
- Modify: `src/renderer/src/components/pathscientist/messages/StageCard.tsx`
- Test: `test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`

**Steps:**
1. Write a failing test with `state.download_progress` and assert the Acquisition disclosure shows percent, bytes, speed, ETA/current file.
2. Add a typed `downloadProgress` view derived from state.
3. Render determinate progress when `bytes_total > 0`, otherwise an animated indeterminate strip with bytes/speed.
4. Run frontend component tests.
