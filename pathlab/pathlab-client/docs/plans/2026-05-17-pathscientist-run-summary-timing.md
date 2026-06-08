# PathScientist Run Summary Timing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a run-level summary card above the PathScientist execution console and stage duration labels in the timeline.

**Architecture:** Keep this as a frontend-derived view feature. Extend `pathscientistEventSelectors.ts` to compute `runSummary` and per-stage timing from session/events/state, then render via a small `RunSummaryCard` component and existing `StageTimeline`.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, Tailwind classes, existing PathScientist selector/view model.

---

### Task 1: Selector View Model

**Files:**
- Modify: `src/renderer/src/lib/pathscientistEventSelectors.ts`
- Test: `test/unit/lib/pathscientistEventSelectors.test.ts`

**Step 1: Write failing tests**
- Add a test with timestamped events across `grounding`, `acquisition`, `execution`, and `completed`.
- Assert `view.runSummary.totalDurationLabel`, `eventCount`, `toolCallCount`, `iterationCount`, `bestMetric`, and `currentActivity`.
- Assert stage `durationLabel` values, including `--` for stages without timestamps.

**Step 2: Run selector test**
Run: `npm run test:run -- test/unit/lib/pathscientistEventSelectors.test.ts`
Expected: FAIL because `runSummary` and stage durations do not exist.

**Step 3: Implement selector code**
- Add `PathScientistRunSummaryView`.
- Add `durationMs` and `durationLabel` to `PathScientistStageView`.
- Add helpers: timestamp parsing, duration formatting, stage timing derivation.
- Add `runSummary` to `PathScientistExecutionView`.

**Step 4: Re-run selector test**
Run: `npm run test:run -- test/unit/lib/pathscientistEventSelectors.test.ts`
Expected: PASS.

### Task 2: UI Rendering

**Files:**
- Create: `src/renderer/src/components/pathscientist/RunSummaryCard.tsx`
- Modify: `src/renderer/src/components/pathscientist/PathScientistExecutionConsole.tsx`
- Modify: `src/renderer/src/components/pathscientist/StageTimeline.tsx`
- Test: `test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`

**Step 1: Write failing component test**
- Assert `Run summary`, total duration, tool call count, iteration count, and best metric render.
- Assert stage timeline renders duration labels.

**Step 2: Run component test**
Run: `npm run test:run -- test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`
Expected: FAIL because the UI does not render those fields.

**Step 3: Implement UI**
- Render `RunSummaryCard` between `StageTimeline` and the two-column console grid.
- Show duration under each stage status in `StageTimeline`.
- Preserve existing PathLab-style card language and compact spacing.

**Step 4: Re-run component test**
Run: `npm run test:run -- test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx`
Expected: PASS.

### Task 3: Verification And Restart

**Files:**
- No additional file changes.

**Step 1: Run focused tests**
Run: `npm run test:run -- test/unit/lib/pathscientistEventSelectors.test.ts test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx test/unit/pages/PathScientistSessionPage.test.tsx`
Expected: PASS.

**Step 2: Restart Vite frontend**
Run the existing Vite restart command with `VITE_API_BASE=/api` and `VITE_DEV_GATEWAY_TARGET=http://127.0.0.1:6100`.

**Step 3: Verify access**
Run: `curl -sS -I -m 5 http://127.0.0.1:5173/pathscientist | head -5`
Expected: HTTP 200.
