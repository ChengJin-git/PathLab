# Unify PathScientist Sessions into PathLab's Background-Task Panel

> Date: 2026-06-18
> Status: Active — design + implementation plan
> Branch context: `fix-pathscientist-persist-web-sessions-work` (the web session model this builds on lives here)
> Goal: make a running PathScientist session show up in the top-right **Background Task** panel like any other
>   PathLab task (training / analysis / storage), with live status, progress, click-through, and cancel.
> Paths: frontend under `src/renderer/src/`, backend under `server/`.

## 1. Problem

PathLab's top-right panel shows live background tasks. PathScientist sessions don't appear there — they live in a
**separate** subsystem (the `auto_research` table + the `/pathscientist/...` routes + per-session SSE), so a user
running a PathScientist research session has no unified "what's running" view.

## 2. How PathLab's panel works today (the pattern to match)

`src/renderer/src/contexts/backgroundTask/` is a **multi-source aggregator**:
- `BackgroundTaskProvider.tsx` merges four streams into one `tasks: BackgroundTask[]` memo:
  `localTasks` (client-side uploads/deletes/migration) + `trainingTasks` + `analysisTasks` + `storageTasks`.
- Each **server** source is one `use*SSE(isLoggedIn, enabled)` hook (`useTrainingSSE`, `useAnalysisSSE`,
  `useStorageSSE`) that opens an `EventSource` to `${API_BASE}/tasks/<type>/stream?token=…`, parses `data.items`,
  and **normalizes each server task into the shared `BackgroundTask` shape** (`types.ts`).
- Subscriptions are **ref-counted / on-demand** (`subscribe*SSE()` → `enabled` flag).
- `useTaskActions.ts` owns cancel/dismiss/remove; dismissed server tasks persist in `localStorage`; finished tasks
  drop off after 10 min.
- `BackgroundTaskPanel.tsx` renders the merged `tasks`.

The normalized contract (`BackgroundTask`): `{ id, type: TaskType, title, items[], status: TaskStatus, totalProgress,
createdAt, completedAt?, isServerTask, serverTaskStatus?, taskName? }`, with
`TaskStatus = pending|running|success|error|cancelled`.

**Key point:** adding a new task kind = (a) a server SSE that emits `{items:[…]}`, (b) a `use*SSE` hook that maps
each item → `BackgroundTask`, (c) merge it in the provider, (d) a new `TaskType` value. PathScientist already has all
the data; it just isn't a source.

## 3. What PathScientist already exposes (the data is ready)

`api/pathscientist.ts` + `types/pathscientist.ts`:
- `listPathScientistSessions()` → `{ items: PathScientistSessionSummary[] }` (GET; user-scoped on the backend).
- `PathScientistSessionSummary` already carries: `session_id, title, question, status
  (queued|running|completed|failed|interrupted), stage, created_at, updated_at, resume_available, error,
  training_progress{current_epoch,total_epochs,current_val_auc,best_val_auc,…}`.
- Per-session SSE: `getPathScientistEventsUrl(sessionId)` → `/pathscientist/sessions/{id}/events`.
- Lifecycle: `stopPathScientistSession`, `resumePathScientistSession`, `deletePathScientistSession`.
- Backend already user-scopes everything (`current_active_user` + `_can_access_record` / `_load_db_session_list(user=…)`).

So the **only** missing pieces are: a *list-level* live feed shaped like the other `/tasks/*/stream` endpoints, and the
frontend wiring to treat a session as a panel task.

## 4. Options

### Option A — Add PathScientist as a 4th SSE source (RECOMMENDED, phase 1)
Mirror the training/analysis/storage pattern exactly. Lowest risk, reversible, no schema change.
- **Pro:** matches the established architecture; isolated; ships fast; the PathScientist detail UI stays as the
  drill-down. **Con:** the panel and the PathScientist sessions page remain two views over the same data (acceptable —
  training already does this and dedupes the SSE).

### Option B — Model-level unification (register sessions as PathLab task rows)
Have the PathScientist session lifecycle also write to PathLab's task model (the `ai_task`/training task table or a new
unified `tasks` row) so it flows through existing aggregation with no new frontend source. The branch's
`pathlab_registration.py` + `training_task_id` linkage already lean this way.
- **Pro:** single source of truth; appears everywhere PathLab tasks appear (panel, task-list page) for free.
  **Con:** dual-write (auto_research + task table) → divergence risk; the PathScientist stage model ≠ training statuses;
  schema/migration; more invasive.

### Option C — Unified Task façade (`/tasks/stream`)
A server-side endpoint that merges training/analysis/storage/pathscientist into one stream; the panel subscribes once.
- **Pro:** cleanest long-term API. **Con:** biggest refactor; touches all existing sources.

### Recommendation
**Phase 1 = Option A** (ship the panel integration now, low risk). **Phase 2 (optional convergence) = Option B/C** once
the task contract is stable — reuse the existing `pathlab_registration` / `training_task_id` linkage to back a unified
task model. Do **not** start with B/C; A delivers the user-visible win immediately and de-risks the contract.

## 5. Implementation (Option A)

### 5.1 Backend — a list-level SSE (mirror `/tasks/training/stream`)
Add a **user-scoped** SSE: `GET /pathscientist/sessions/stream?token=…` (or `/tasks/pathscientist/stream` to sit beside
the others) in `server/gateway/routes/pathscientist.py`. It emits, on change + heartbeat:
```json
{ "items": [ { "task_id", "task_name", "task_type": "research", "mode": "research|code",
              "status", "stage", "progress", "created_at", "finished_at", "session_id",
              "resume_available", "error" } ] }
```
- Source the list from the existing `_SESSION_MANAGER.list()` + `_load_db_session_list(user=…)` (already user-scoped),
  reusing `record.summary()`; filter by the authenticated user.
- **Server owns the status/progress normalization** (keep the frontend dumb) — see §5.3.
- Reuse the SSE/auth plumbing already in `stream_session_events` (`get_user_from_token_param`).
- **Interim shortcut (Phase 1a):** skip the new endpoint and have the frontend **poll** `listPathScientistSessions()`
  every 3–5 s (exactly how the migration task polls `getMigrationStatus`). Ship the panel integration first; upgrade to
  SSE in Phase 1b. (Polling is also a safe fallback if the per-user broadcast is more work than expected.)

### 5.2 Frontend — wire it as a source
In `src/renderer/src/contexts/backgroundTask/`:
1. `types.ts`: add `'research'` to `TaskType`; add optional fields to `BackgroundTask`:
   `sessionId?: string`, `researchStage?: string`, `resumeAvailable?: boolean`.
2. New `usePathScientistSSE.ts` (copy `useTrainingSSE.ts`): connect to the stream (or poll the list), map each item →
   `BackgroundTask` (`id: \`research_${session_id}\``, `type: 'research'`, `title`, single `item`, `status`,
   `totalProgress`, `isServerTask: true`, `serverTaskStatus: status`, `sessionId`, `researchStage: stage`).
3. `BackgroundTaskProvider.tsx`: add `subscribePathScientistSSE()` (ref-counted, like the others), call
   `const { pathscientistTasks } = usePathScientistSSE(isLoggedIn, pathscientistSSEEnabled)`, and merge
   `...pathscientistTasks` into the `tasks` memo (respecting `dismissedServerTasks` + the 10-min finished window).
   Expose `subscribePathScientistSSE` on the context value (`types.ts` `BackgroundTaskContextType`).
4. `useTaskActions.ts`: in `cancelServerTask`, branch on `task.type === 'research'` → `stopPathScientistSession(task.sessionId)`;
   `removeTask` already handles dismissal.
5. `BackgroundTaskPanel.tsx`: render the `research` row (reuse the server-task row); **clicking navigates to the existing
   PathScientist session page** `/pathscientist/sessions/{sessionId}` (the drill-down detail view already exists). Show
   the stage label + progress; show a Resume affordance when `resumeAvailable`.
6. Whoever launches a session (the PathScientist new-session page) should call `subscribePathScientistSSE()` (or the
   panel subscribes whenever any research session is active) so the stream connects on demand.
7. i18n: add `backgroundTask.taskTitles.research` (+ stage labels) to `locales/{en-US,zh-CN,zh-HK}.json`.

### 5.3 Status & progress mapping (server-owned normalizer)
Map a PathScientist session to the panel contract in **one** backend function (`session_to_task_item`):

| session.status | TaskStatus |
|---|---|
| queued | pending |
| running | running |
| completed | success |
| failed | error |
| interrupted | cancelled |

Progress (0–100), **stage-weighted bands** (server computes; example bands):

| stage | band | within-band refinement |
|---|---|---|
| grounding | 0–10 | — |
| acquisition | 10–30 | download_progress if present |
| readiness / pre_execution_ready | 30–40 | — |
| execution | 40–90 | `iteration_index / max_iterations`, refined by `training_progress.current_epoch/total_epochs` |
| review | 90–92 | — |
| synthesis | 92–100 | — |
| completed | 100 | — |

`serverTaskStatus`/`researchStage` carry the human stage label for the row; the panel stays a compact rollup — **one
task per session**, not one per stage/iteration/run (the PathScientist page is the detail view).

## 6. Design decisions / edge cases
- **Granularity:** one panel row per *session*. Don't explode stages/runs into separate tasks.
- **Single connection:** like training (which feeds both the panel and the TaskList page from one SSE via
  `rawTrainingTasks`), expose the raw sessions so the PathScientist sessions page can reuse the same stream and avoid a
  second connection.
- **User scoping:** the stream/list must filter to the current user (backend already enforces this).
- **Finished window + dismiss:** reuse the existing 10-min finished filter + `dismissedServerTasks` localStorage set.
- **Cancel/resume:** `research` → `stopPathScientistSession`; surface Resume when `resume_available`.
- **Reconnect/auth:** reuse `useTrainingSSE`'s `onerror`/`getCurrentUser()` 401 handling.
- **Code mode:** a `mode:'code'` session is the same task type (`research`) with a different label.
- **Naming:** `id = research_<session_id>`; ensure no collision with `training_`/`extval_` prefixes (already namespaced).

## 7. Testing
- Frontend (Vitest): a `usePathScientistSSE` test feeding mock items → asserts `BackgroundTask` mapping & status/progress;
  a provider test asserting research tasks merge + dismiss + finished-window behavior.
- Backend: a route test for the stream/list emitting only the caller's sessions with the normalized shape
  (extend `server/tests/test_pathscientist_routes.py`).
- Manual: start a session → row appears in the panel with live stage/progress → click opens the session page →
  cancel from the panel stops it → completion drops off after 10 min.

## 8. Task breakdown

| ID | Area | Task | Effort |
|---|---|---|---|
| U1 | FE | `types.ts`: add `research` TaskType + `sessionId/researchStage/resumeAvailable` | S |
| U2 | FE | `usePathScientistSSE.ts` (poll list first; SSE later) + map → `BackgroundTask` | M |
| U3 | FE | Provider: `subscribePathScientistSSE` + merge into `tasks` memo | S |
| U4 | FE | `useTaskActions`: cancel/resume for `research` | S |
| U5 | FE | `BackgroundTaskPanel`: render row + click-through to session page + i18n | M |
| U6 | BE | `session_to_task_item` normalizer (status + stage-weighted progress) | S |
| U7 | BE | `GET /pathscientist/sessions/stream` user-scoped SSE emitting `{items:[…]}` (Phase 1b; Phase 1a = polling) | M |
| U8 | — | Tests (FE hook/provider + BE route) | M |
| U9 | docs | Note in master plan that PathScientist tasks now surface in the unified panel | S |

## 9. Phase 2 (optional convergence — Option B/C)
Once the contract is stable, back the panel from a **unified task model** instead of a per-source hook:
- promote the `auto_research` session ↔ `training_task_id` linkage (already started in `pathlab_registration.py`) into a
  first-class task row, or a `/tasks/stream` façade that merges all sources server-side;
- then the PathScientist row needs no dedicated frontend hook — it arrives through the same channel as training/analysis.
Treat this as a follow-up, not a blocker for the Phase-1 user-visible integration.
