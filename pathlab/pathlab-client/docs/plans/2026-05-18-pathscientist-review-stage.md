# PathScientist Review Stage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the PathScientist `review` stage a real deterministic post-execution review that records decisions, summaries, and next actions instead of a millisecond-only route checkpoint.

**Architecture:** Add a deterministic review engine in `server/backend/pathscientist/orchestrator/review.py` that inspects `ResearchSessionState.run_history`, budget, stop reason, and per-turn activity counters. Persist review output on `ResearchSessionState` as `latest_review`, `review_history`, and `review_decision`; keep `ResearchDirector` as a state machine that follows the review decision with the previous budget/stop fallback. Surface review data through the Gateway live/persisted state and render it in the existing frontend stage card.

**Tech Stack:** Python dataclasses + pytest for backend orchestration tests; TypeScript/Vitest for frontend selector tests; existing React UI cards.

---

### Task 1: Backend Review Engine

**Files:**
- Create: `server/backend/pathscientist/orchestrator/review.py`
- Modify: `server/backend/pathscientist/orchestrator/types.py`
- Test: `server/backend/pathscientist/tests/test_review_stage.py`

**Step 1: Write failing tests**
- Test committed metric improvement produces `status="improved"`, `decision="continue_execution"`, metric delta, and summary.
- Test budget exhaustion produces `decision="enter_synthesis"` and sets `stop_reason="budget_exhausted"` when missing.
- Test no finalized run produces `status="no_finalized_run"`, captures action/stall context, and continues unless a stop reason exists.

**Step 2: Run tests to verify fail**
Run: `OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest backend/pathscientist/tests/test_review_stage.py -q`
Expected: FAIL because `pathscientist.orchestrator.review` does not exist.

**Step 3: Implement minimal review engine**
- Add `ReviewRecord` dataclass with `to_dict()`.
- Add `run_review_stage(state, previous_best_value, previous_run_count, action_events=0, dropped_entries=0)`.
- Append record dict to `state.review_history`, set `state.latest_review`, set `state.review_decision`.

**Step 4: Run tests to verify pass**
Run the same pytest command; expected PASS.

---

### Task 2: State Persistence and Director Decision

**Files:**
- Modify: `server/backend/pathscientist/orchestrator/types.py`
- Modify: `server/backend/pathscientist/orchestrator/state_bridge.py`
- Modify: `server/backend/pathscientist/orchestrator/director.py`
- Test: `server/backend/pathscientist/tests/test_research_director.py`
- Test: `server/backend/pathscientist/tests/test_state_bridge_execution_plan.py`

**Step 1: Write failing tests**
- Director uses `latest_review.decision == "enter_synthesis"` to advance review to synthesis.
- Director uses `latest_review.decision == "continue_execution"` to advance review to execution.
- State bridge round-trips `latest_review`, `review_history`, and `review_decision`.

**Step 2: Run tests to verify fail**
Run targeted pytest for those tests; expected FAIL because fields/logic are absent.

**Step 3: Implement minimal code**
- Add fields to `ResearchSessionState`.
- Hydrate them in `load_research_session_state`.
- Update director review branch to prefer `latest_review.decision` with old fallback.

**Step 4: Run tests to verify pass**
Run targeted pytest; expected PASS.

---

### Task 3: Runner Integration

**Files:**
- Modify: `server/backend/pathscientist/orchestrator/runner.py`
- Test: `server/backend/pathscientist/tests/test_orchestrator_runner.py`

**Step 1: Write failing source-level or unit test**
- Verify runner imports/calls `run_review_stage` after `state.advance("review")` and before `director.advance(state)`.

**Step 2: Run test to verify fail**
Run: `OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest backend/pathscientist/tests/test_orchestrator_runner.py -q -k review`
Expected: FAIL.

**Step 3: Implement runner calls**
- Capture `previous_best_value` and `previous_run_count` before processing new tracker history.
- Capture `action_events`/`dropped_entries`.
- Call `run_review_stage` in both `run_research_session` and `continue_research_session` immediately after advancing to review.
- Persist state after review record creation.

**Step 4: Run test to verify pass**
Run targeted pytest; expected PASS.

---

### Task 4: Gateway and Frontend Surfacing

**Files:**
- Modify: `server/gateway/routes/pathscientist.py`
- Modify: `src/renderer/src/lib/pathscientistEventSelectors.ts`
- Test: `server/tests/test_pathscientist_routes.py`
- Test: `test/unit/lib/pathscientistEventSelectors.test.ts`

**Step 1: Write failing tests**
- Gateway live/persisted state includes `latest_review`, `review_history`, `review_decision`.
- Frontend Review stage summary comes from `latest_review.summary` when no real review event exists.
- Duration formatter shows `<1s` for positive sub-second durations.

**Step 2: Run tests to verify fail**
Run backend and frontend targeted tests; expected FAIL.

**Step 3: Implement minimal surfacing**
- Add review fields to Gateway state projection.
- In selector `buildStages`, use `latest_review.summary` for review stage summary fallback.
- Adjust `formatDuration` to return `<1s` for positive durations under one second.

**Step 4: Run tests to verify pass**
Run targeted backend/frontend tests; expected PASS.

---

### Task 5: Verification

**Files:**
- All touched files.

**Step 1: Run backend tests**
`cd server && OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest backend/pathscientist/tests/test_review_stage.py backend/pathscientist/tests/test_research_director.py backend/pathscientist/tests/test_state_bridge_execution_plan.py backend/pathscientist/tests/test_orchestrator_runner.py tests/test_pathscientist_routes.py -q`

**Step 2: Run frontend tests**
`npm run test:run -- test/unit/lib/pathscientistEventSelectors.test.ts test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`

**Step 3: Restart only if no run is active**
Check `/pathscientist/sessions` for queued/running sessions. If none, restart backend so the changed Gateway and orchestrator code is loaded.
