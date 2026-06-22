# PathScientist Grounding Literature Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show the papers and task evidence produced by Grounding in the PathScientist execution console.

**Architecture:** The Gateway projects `research_session.grounding` into the session `state` for both live and persisted sessions. The frontend selector normalizes a compact `grounding` view from either `state.grounding` or `state.persisted_summary.research_session.grounding`, and `StageCard` renders the Grounding stage as task routing plus literature evidence instead of a single generic sentence.

**Tech Stack:** FastAPI route projection tests with pytest; React + TypeScript selector/component tests with Vitest and Testing Library.

---

### Task 1: Backend Grounding Projection

**Files:**
- Modify: `server/gateway/routes/pathscientist.py`
- Test: `server/tests/test_pathscientist_routes.py`

**Step 1: Write failing tests**
- Add one test that `_build_live_progress_state` includes `grounding` from `research_session`.
- Add one assertion that `_build_persisted_session_state` exposes `research_session.grounding` at top-level `state["grounding"]`.

**Step 2: Verify red**
- Run: `cd server && OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest tests/test_pathscientist_routes.py -q -k 'live_progress_state_projects_current_stage_from_agent_state or builds_legacy_state_from_summary'`
- Expected: FAIL because `grounding` is missing.

**Step 3: Implement minimal projection**
- Add `grounding: _as_payload_dict(research.get("grounding"))` to live state.
- Add `state["grounding"] = grounding` when persisted `research_session.grounding` is a dict.

**Step 4: Verify green**
- Re-run the same pytest command.

### Task 2: Frontend Grounding Selector

**Files:**
- Modify: `src/renderer/src/lib/pathscientistEventSelectors.ts`
- Test: `test/unit/lib/pathscientistEventSelectors.test.ts`

**Step 1: Write failing test**
- Build a session state with `grounding.task_profile`, `selected_skill`, `online_literature_count`, `papers`, and `sota_lookup_status`.
- Assert `view.grounding` contains the task profile, count, papers, and a no-SOTA status label.

**Step 2: Verify red**
- Run: `npm run test:run -- test/unit/lib/pathscientistEventSelectors.test.ts`
- Expected: FAIL because `view.grounding` does not exist.

**Step 3: Implement minimal selector**
- Add `PathScientistGroundingView` and `PathScientistGroundingPaperView` types.
- Extract `grounding` from `state.grounding` with fallback to `state.persisted_summary.research_session.grounding`.
- Normalize up to 8 papers with title/year/source/url/provider.

**Step 4: Verify green**
- Re-run selector test.

### Task 3: Grounding Stage UI

**Files:**
- Modify: `src/renderer/src/components/pathscientist/messages/StageCard.tsx`
- Modify: `src/renderer/src/components/pathscientist/PathScientistExecutionConsole.tsx`
- Test: `test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`

**Step 1: Write failing test**
- Render a session with `state.grounding.papers`.
- Assert the Grounding card shows `Grounding literature`, paper title, source/year, selected skill, and task profile.

**Step 2: Verify red**
- Run: `npm run test:run -- test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`
- Expected: FAIL because papers are not rendered.

**Step 3: Implement minimal UI**
- Pass `view.grounding` into Grounding `StageCard` only.
- Render a compact task routing strip and up to 5 paper rows.
- Avoid collapse behavior; keep links safe with `target="_blank" rel="noreferrer"`.

**Step 4: Verify green**
- Re-run component test.

### Task 4: Final Verification

**Files:**
- No production changes.

**Step 1: Run targeted backend tests**
- `cd server && OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest tests/test_pathscientist_routes.py -q`

**Step 2: Run targeted frontend tests**
- `npm run test:run -- test/unit/lib/pathscientistEventSelectors.test.ts test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`

**Step 3: Manual spot check**
- Fetch latest session detail and confirm `state.grounding.papers` exists.
- If frontend is running, Vite HMR should apply the change without restart.
