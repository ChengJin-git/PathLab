# PathScientist LLM Run Summary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show a holistic LLM-generated run summary that explains the user request, agent work, and final result.

**Architecture:** Persist a structured `ui_run_summary` in `ResearchSessionState`, generate it after synthesis with GPT-5.5 and a deterministic fallback, expose it through the gateway state payload, and render the frontend summary card from that structured data. The frontend must never use the latest event/activity message as the run narrative.

**Tech Stack:** Python dataclasses and pytest for backend state/orchestrator tests; React/TypeScript/Vitest for frontend selector and component tests.

---

### Task 1: Frontend selector behavior

**Files:**
- Modify: `test/unit/lib/pathscientistEventSelectors.test.ts`
- Modify: `src/renderer/src/lib/pathscientistEventSelectors.ts`

**Steps:**
1. Add a failing selector test where `state.ui_run_summary` contains `user_request`, `agent_actions`, `result`, `brief`, and a long final agent message appears in events.
2. Assert `view.runSummary.narrative` uses the structured backend fields and does not use the long final message.
3. Implement the minimal selector fields and fallback narrative builder.
4. Run the focused selector tests.

### Task 2: Frontend card rendering

**Files:**
- Modify: `test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`
- Modify: `src/renderer/src/components/pathscientist/RunSummaryCard.tsx`

**Steps:**
1. Add a failing component assertion for `User request`, `Agent work`, and `Result` sections.
2. Update the card to render narrative sections and remove `currentActivityLabel` as the summary body.
3. Keep metric/task/foundation/MIL tiles.
4. Run focused component tests.

### Task 3: Backend state persistence

**Files:**
- Modify: `server/backend/pathscientist/orchestrator/types.py`
- Modify: `server/backend/pathscientist/orchestrator/state_bridge.py`
- Modify: `server/backend/pathscientist/tests/test_stage_timing.py` or new backend test
- Modify: `server/tests/test_pathscientist_routes.py`

**Steps:**
1. Add failing tests that `ui_run_summary` round-trips through state bridge and appears in gateway legacy detail state.
2. Add `ui_run_summary: dict` to `ResearchSessionState` and state loading.
3. Expose `research_session.ui_run_summary` from gateway persisted state builder.
4. Run focused backend tests.

### Task 4: Backend generation

**Files:**
- Create: `server/backend/pathscientist/orchestrator/ui_summary.py`
- Modify: `server/backend/pathscientist/orchestrator/runner.py`
- Add/modify backend tests for summary generation fallback/parsing.

**Steps:**
1. Add tests for deterministic fallback and JSON parsing of an LLM response.
2. Implement `build_ui_run_summary(...)` using GPT-5.5 via `llm_client`, JSON output, and safe fallback.
3. Call it after `final_summary` is built and before final persistence.
4. Run focused backend tests.

### Task 5: Verification and restart

**Commands:**
- `npm run test:run -- test/unit/lib/pathscientistEventSelectors.test.ts test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx test/unit/pages/PathScientistSessionPage.test.tsx`
- `cd server && backend/pathscientist/.venv/bin/python -m pytest ... -q`
- Restart backend and frontend dev services.
