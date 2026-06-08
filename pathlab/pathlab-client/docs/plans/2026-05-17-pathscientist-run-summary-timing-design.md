# PathScientist Run Summary And Stage Timing Design

**Goal:** Add a compact run summary card above the execution transcript and show per-stage duration in the stage timeline.

**Approved approach:** Derive the summary and timings on the frontend from persisted normalized events, session state, and existing selector outputs. This avoids API/schema changes and works for old sessions when event timestamps are present.

**Data flow:** `buildPathScientistExecutionView()` computes `runSummary` and enriches each `stage` with `durationMs`/`durationLabel`. React components render those values without recomputing data.

**Summary card content:** title/status, total duration, visible event count, tool call count, iteration count, best metric/run id, task type, foundation model, optional MIL method, and current activity.

**Timing rules:** stage start is the first event timestamp for that stage; stage end is the next stage's first timestamp, or the latest visible event timestamp for the final active stage. Missing timestamps display `--`.

**Testing:** Add selector tests for derived summary/timings and component tests that assert the summary card and duration labels render.
