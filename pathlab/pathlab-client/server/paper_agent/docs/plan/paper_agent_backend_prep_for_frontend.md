# Backend Prep Plan — Before Frontend Work Starts

> 创建日期：2026-05-06
> 最后更新：2026-05-06（更新 §10：发现 1.5 / 1.6 已通过 tests/gateway_interface/ 落地；Wave 0 实际完成 2/4）
> 状态：proposal
> 配套文档：paper_agent_frontend_design.md

This plan lists the backend work that should land before the frontend paper
workspace becomes the primary user surface. It is aligned with the current
standalone Paper Agent implementation under `server/paper_agent/`, the Gateway
compatibility mount, and the current decision that a public paper-writing run
uses **one user-selected target template**.

---

## 1. Scope

In scope:

- API response fields the frontend reads directly.
- Manifest, artifact, stage-log, outline, figure, and validation contracts.
- Backend correctness checks needed for PDF preview and export download.
- Worker/API changes needed for v2 interactive features.

Out of scope:

- New LLM agents.
- Storage migration; keep `uploads/paper_generation/{paper_id}/...`.
- Auth model rework; route-level ownership/admin checks already exist.
- Changing the evidence/locked-block/citation/metric safety contracts.

---

## 2. Current baseline

Current API surface:

| Endpoint | Status | Notes |
|---|---|---|
| `POST /papers` | shipped | DB row + scaffold + worker enqueue best-effort |
| `GET /papers` | shipped | paginated and scoped to caller |
| `GET /papers/{id}` | shipped | summary + artifacts + stage log; `validation_summary` still `None` |
| `GET /papers/{id}/sections` | shipped | editable section list with hash + mtime |
| `POST /papers/{id}/sections/{name}/regenerate` | shipped | synchronous in-process regenerate |
| `DELETE /papers/{id}` | shipped | DB + filesystem deletion |
| `GET /papers/{id}/files?path=...` | shipped | allowlisted public file download |

Current pipeline stages:

```text
collecting -> building_evidence -> outlining -> plotting -> literature_review
-> section_writing -> validating -> refining -> rendering -> exporting
```

Current public template policy:

- Public API accepts exactly one `selected_templates` entry.
- User-facing choices are `miccai` or `nature_scientific_reports`.
- Internal tests may still construct multi-template configs to regression-test
  renderer/exporter assets, but that is not the public UX contract.

Current known frontend-facing gaps:

- `GET /papers/{id}.validation_summary` is not populated.
- `stage_log` has only loose `{stage, ts, message}` entries and no duration.
- `artifact_index` and `stage_log` are loose dicts rather than typed contract
  models.
- Outline and figures manifests do not yet have exported public Pydantic
  schemas for frontend type generation.
- Regenerate is synchronous.
- Outline approve/pause/resume, per-stage rerun, and cancel are not implemented.

---

## 3. Phase 0 — PDF/export verification, not a new implementation task

Earlier versions of this plan listed two PDF blockers. Both implementation
issues are already addressed in the current codebase:

- Docker compile now lives under `server/paper_agent/docker/paper-latex/` and
  uses `latexmk -pdf`, which handles BibTeX/re-runs automatically.
- `bundle_validator.py` no longer passes the invalid `-dvi=0 -ps=0` flags; it
  relies on `latexmk -pdf`.

Remaining Phase 0 work is therefore verification:

### 0.1 Verify resolved citations in compiled PDFs

- Run a Docker-enabled compile/export smoke test on a representative paper run.
- Confirm generated PDFs do not show unresolved `[?]` citations.
- Confirm the References section is populated when `refs.bib` has selected
  references.
- Acceptance:
  - `final/{template}/main.pdf` exists;
  - `final/{template}/main.compile_summary.txt` shows successful compile;
  - a manual or automated PDF text check confirms citations/references are not
    empty.
- Estimate: 0.5 day.

### 0.2 Verify downloadable export bundles

- Run bundle validation on `exports/{template}_bundle.zip`.
- Confirm bundle contains public dependencies and excludes private evidence.
- Acceptance:
  - `BundleValidationResult(status="passed", downloadable=True)` for a normal
    run;
  - private files remain excluded.
- Estimate: 0.5 day.

Phase 0 can run in parallel with Phase 1.

---

## 4. Phase 1 — v1.5 read-only frontend contract

Frontend v1.5 can ship with existing endpoints if these response contracts are
hardened first.

### 1.1 Populate `validation_summary` in `GET /papers/{id}`

Current state:

- `GET /papers/{id}` always returns `validation_summary=None`.
- Validation data exists on disk, not in `manifest.validation_summary`.

Source files to aggregate:

```text
validation/metric_guard.json
validation/identifier_guard.json
validation/latex_guard.json
validation/citation_guard.json
validation/claim_guard.json
validation/consistency_guard.json
validation/warnings.md
validation/refinement_log.json
```

Proposed response shape:

```python
class GuardResultSummary(BaseModel):
    guard: str
    status: str
    issue_count: int
    error_count: int
    warning_count: int
    path: str | None = None

class RefinementSummary(BaseModel):
    final_status: str | None = None
    max_iterations: int | None = None
    accepted_iterations: list[int] = []
    iteration_count: int = 0
    initial_score: dict | None = None
    final_score: dict | None = None
    log_path: str | None = "validation/refinement_log.json"

class ValidationSummary(BaseModel):
    m10_guards: list[GuardResultSummary] = []
    refinement: RefinementSummary | None = None
    hybrid_score: float | None = None
    warnings_md_path: str | None = "validation/warnings.md"
```

Rules:

- If a run has not reached validation, return empty guards and `hybrid_score=None`.
- Do not expose private guard JSONs through `/files`; summarize them in the API
  response only.
- `warnings_md_path` may be downloadable only when registered public in the
  manifest.

Acceptance:

- `GET /papers/{id}` returns a non-null `validation_summary` after validation.
- Partial runs return a stable empty summary instead of `None`.
- Tests cover both partial and validated/refined runs.

Estimate: 1 day.

### 1.2 Add structured stage timings

Current state:

- `stage_log` entries are loose dicts: `{stage, ts, message}`.
- The timestamp is captured before stage execution, so it cannot represent a
  reliable completion time.

Proposed completed-stage entry:

```json
{
  "stage": "outlining",
  "status": "completed",
  "started_at": "2026-05-06T...Z",
  "finished_at": "2026-05-06T...Z",
  "duration_ms": 12345,
  "message": "Stage outlining completed."
}
```

Failure entry:

```json
{
  "stage": "outlining",
  "status": "failed",
  "started_at": "...",
  "finished_at": "...",
  "duration_ms": 12345,
  "message": "Stage outlining failed: ...",
  "error_message": "..."
}
```

Compatibility:

- Keep `ts` for older clients for one release if needed, but frontend should use
  `started_at`, `finished_at`, and `duration_ms`.

Acceptance:

- StageChecklist can render per-stage duration without inspecting artifacts.
- Tests assert `duration_ms` exists and is non-negative for successful and
  failed stages.

Estimate: 0.5-1 day.

### 1.3 Define the manifest/artifact contract

Current state:

- `PaperManifest.artifact_index` is `dict[str, Any]`.
- Stage log entries are loose dicts.
- Frontend must infer fields instead of importing a stable schema.

Backend work:

- Add Pydantic models in `schemas.py`:
  - `PaperArtifactIndexEntry`
  - `PaperStageLogEntry`
  - `ValidationSummary`
  - supporting summary models used by `GET /papers/{id}`
- Keep `artifact_index` storage backwards-compatible, but validate entries when
  reading/writing through helper functions.
- Document public/private meanings:
  - `status`
  - `visibility`
  - `downloadable`
  - `label`
  - `content_type`

Acceptance:

- Every field rendered by the frontend exists in a backend Pydantic model.
- `PaperRunDetail` OpenAPI output is enough to generate frontend types.

Estimate: 1 day.

### 1.4 Define Outline and Figure manifest schemas

Current state:

- `drafts/outline.json` and `figures/manifest.json` have implicit schemas inside
  their writing agents.
- Frontend v1.5 reads them through `/files`; v2 will edit outline content.

Backend work:

- Add exported Pydantic models in `schemas.py` or a dedicated public schema
  module:
  - `OutlineDocument`
  - `OutlineSectionPlanItem`
  - `OutlinePlottingPlanItem`
  - `FigureManifest`
  - `FigureManifestItem`
- Phase 1 only needs validation/type export. Do not force every agent write path
  through these models in the first patch unless it is low-risk.
- Add tests that current generated `outline.json` and `figures/manifest.json`
  validate against these models.

Acceptance:

- Frontend can generate or mirror TS types for outline and figures.
- Current pipeline output validates without large agent rewrites.

Estimate: 1 day.

### 1.5 Audit `/files` allowlist and manifest registration

Current state:

- The allowlist already includes the main frontend surfaces:
  - `drafts/outline.json`
  - `figures/`
  - `validation/warnings.md`
  - `final/`
  - `exports/`
- `/files` additionally requires manifest registration as public/downloadable.

Backend work:

- Add/confirm tests for every file the v1.5 frontend reads.
- Confirm no private artifact is registered public accidentally.
- Ensure `figures/manifest.json` and `drafts/outline.json` are registered public
  when produced.

Acceptance:

- Frontend-visible files return 200 through `/files` after the relevant stage.
- Private/internal files return 403.

Estimate: 0.5 day.

### 1.6 Confirm single-template frontend contract

Decision:

- Keep the current public API rule: exactly one target template per run.
- Frontend create UI should be a single-select control.
- No PDF Preview template switcher is needed for v1.5.

Acceptance:

- Frontend design doc states single-template generation.
- Backend tests assert multi-template create requests return 400.
- Renderer/exporter internal multi-template tests remain allowed, with comments
  explaining that they are implementation regression tests.

Estimate: 0.25 day.

**Phase 1 total: ~4-5 days.**

---

## 5. Phase 2 — v2 interactive backend

These changes are needed for bidirectional frontend features.

### 2.1 Outline approve gate

Current state:

- `complete_run()` runs the full stage sequence in one worker job.
- There is no pause after outlining.

Recommended design: split worker jobs.

- Job A: `paper_generation.run_until_outline`
  - runs `collecting -> building_evidence -> outlining`;
  - marks run as waiting for outline approval.
- Endpoint: `PUT /papers/{id}/outline`
  ```python
  body: {outline: OutlineDocument, approve: bool}
  response: {paper_id, approved, current_stage}
  ```
- If `approve=False`, save outline edits only.
- If `approve=True`, save outline, mark approved, enqueue Job B.
- Job B: `paper_generation.run_after_outline`
  - runs `plotting -> literature_review -> section_writing -> validating -> refining -> rendering -> exporting`.

Avoid worker polling unless the existing worker system has a standard pause/resume
primitive. Split jobs are easier to reason about and align with current dispatch.

Acceptance:

- A run can pause after outlining.
- User can edit and approve outline.
- Approval enqueues post-outline job.
- Integration test covers pause/edit/approve/resume.

Estimate: 5-7 days.

### 2.2 Async section regenerate

Current state:

- `POST /papers/{id}/sections/{name}/regenerate` runs synchronously in the HTTP
  request.

Target behavior:

- HTTP returns `202 Accepted` quickly with a `regen_id` or job id.
- Worker handles `paper_generation.regenerate_section`.
- Frontend polls `GET /papers/{id}` or a future job endpoint.

Request body extension:

```python
class RegenerateSectionRequest(BaseModel):
    target_paragraph: int | None = None
    user_note: str | None = None
    target_section: str | None = None
```

Acceptance:

- Existing sync behavior is either preserved behind a dev/test flag or replaced
  with updated tests.
- New tests assert `202` and worker enqueue.

Estimate: 2-3 days.

### 2.3 Per-stage rerun endpoint

New endpoint:

```text
POST /papers/{id}/stages/{stage}:run
```

Behavior:

- Enqueue `paper_generation.run_stage` rather than running in request.
- Reject with 409 if the run is currently running.
- Mark downstream artifacts stale instead of deleting them silently.
- Do not implicitly rerun downstream stages; caller/frontend controls sequence.

Acceptance:

- Rerunning `outlining` produces a fresh `outline.json`.
- Existing downstream sections/final/export artifacts remain but are flagged stale.
- Stage log records rerun reason and timing.

Estimate: 2 days.

### 2.4 Cancel endpoint

New endpoint:

```text
POST /papers/{id}:cancel
```

Behavior:

- Set DB + manifest status to `cancelled`.
- Append a stage log entry.
- Ask worker to cooperatively abandon in-flight work if supported.
- If cooperative cancellation is not supported yet, implement best-effort state
  marking first and document that the running subprocess may finish late.

Acceptance:

- Running paper can be marked cancelled.
- Subsequent polling returns `status=cancelled`.
- Worker does not overwrite a cancelled manifest on late completion.

Estimate: 1-2 days.

**Phase 2 total: ~10-15 days.**

---

## 6. Recommended execution order

```text
Week 1
  ├─ Phase 0 verification                 [0.5-1d]
  ├─ Phase 1.1 validation_summary          [1d]
  ├─ Phase 1.2 stage timings               [0.5-1d]
  └─ Phase 1.3 manifest/artifact contract  [1d]
       -> Frontend v1.5 can start against stable run/detail types

Week 1-2
  ├─ Phase 1.4 outline + figure schemas    [1d]
  ├─ Phase 1.5 files allowlist audit        [0.5d]
  └─ Phase 1.6 single-template docs/tests   [0.25d]
       -> Frontend v1.5 read-only workspace fully unblocked

Week 2-4
  └─ Phase 2.1 outline approve gate         [5-7d]
       -> Frontend v2 outline editor unblocked

Week 4-5
  ├─ Phase 2.2 async regenerate             [2-3d]
  ├─ Phase 2.3 per-stage rerun              [2d]
  └─ Phase 2.4 cancel                       [1-2d]
       -> Frontend v2 interactive workspace fully unblocked
```

---

## 7. Open decisions

1. **Stage stale semantics**: When a user reruns an upstream stage, which
   downstream artifacts get `stale=true`, and where is that stored?
2. **Worker cancellation**: Does the current worker support cooperative cancel,
   or do we need a new job-state primitive?
3. **Validation summary detail level**: Should the detail endpoint include only
   counts/status, or also first N issue messages? Recommendation: include counts
   plus first 3 public-safe messages per guard.
4. **Outline approve storage**: Should approval state live only in manifest, or
   also in a small `drafts/outline_approval.json` marker? Recommendation:
   manifest for API state, marker file only if worker needs filesystem-only
   resume.
5. **Async regenerate progress**: Is polling `GET /papers/{id}` enough, or do we
   want a job-level endpoint later?

---

## 8. Explicit non-goals

Do not change these contracts for the frontend rewrite:

- Run layout under `uploads/paper_generation/{paper_id}/...`.
- Evidence lock and public evidence split.
- Locked-block contract.
- Metric placeholder contract.
- Citation verification and coverage contract.
- Public/private export boundary.
- Single-template public paper-writing request policy.
- Existing 9-stage pipeline names.

If one of these appears to block frontend work, pause and redesign rather than
mutating the contract ad hoc.

---

## 9. Multi-agent execution

### 9.0 Pre-Phase 0 — ownership transfer (already landed in working tree)

Before Phase 0 starts, paper-agent's API contract has been moved out of
Gateway into `server/paper_agent/`:

- `pathlab_paper_agent/schemas.py` is now self-contained (no longer
  re-exports from `gateway.paper_generation.schemas`).
- `pathlab_paper_agent/storage.py` owns `PaperRunPaths`, the public
  download allowlist, and `safe_resolve` end-to-end.
- `pathlab_paper_agent/api/routes.py` is the FastAPI router itself;
  `gateway/paper_generation/routes.py` is now a 16-line proxy that does
  `from pathlab_paper_agent.api.routes import router`.
- `pathlab_paper_agent/scaffold.py` owns `initialize_paper_run`.

Implication for the wave plan: contract changes for Phase 1 can land
inside `server/paper_agent/` without coordinating with Gateway. The
Wave 1 contract-owner agent only needs to touch one tree.

This commit also makes Phase 1.6 effectively zero-cost: the
"exactly one template" rule already lives in `api/routes.py:238-242`,
and the schema default in `CreatePaperRequest.selected_templates` is
already `[miccai]`. Wave 0 just needs to add explicit assertion tests.

### 9.1 Wave structure

Designed around the only real conflict surface: `schemas.py`. Phase 1.1,
1.3, and 1.4 all add Pydantic models there, so they cannot run in
parallel agents without merge churn. Everything else is well-isolated.

```text
Wave 0  (~0.5d, 4 agents parallel)
  A  Phase 0.1 verify resolved citations smoke test
  B  Phase 0.2 verify downloadable bundles smoke test
  C  Phase 1.5 add explicit allowlist tests
  D  Phase 1.6 add single-template assertion tests in test suite
  → all changes are tests / verification only; no shared file conflicts.

Wave 1  (~1-2d, 1 contract-owner agent on schemas.py)
  E  Phase 1.3 PaperArtifactIndexEntry, PaperStageLogEntry
     Phase 1.4 OutlineDocument, OutlineSectionPlanItem,
                OutlinePlottingPlanItem, FigureManifest, FigureManifestItem
     Phase 1.1 GuardResultSummary, RefinementSummary, ValidationSummary
  → one PR, one review, schemas.py touched once.
  → no endpoint or pipeline write-side changes in this wave.

Wave 2  (~1-2d, 2 agents parallel after Wave 1 merges)
  F  Phase 1.1 endpoint: aggregate validation/*.json into ValidationSummary
                in GET /papers/{id}; replace `validation_summary=None` in
                routes.py
  G  Phase 1.2 stage timestamps: write started_at/finished_at/duration_ms
                from pipeline.py; emit completed/failed entries that
                validate against PaperStageLogEntry
  → F touches api/routes.py (single GET handler) + new aggregator helper.
  → G touches pipeline.py (run_stage timing) only.
  → Phase 1 done. Frontend v1.5 unblocked.

Wave 3  (~5-7d, up to 4 agents; 2.1 is the critical path)
  H  Phase 2.1 outline approve gate (split jobs: run_until_outline +
                run_after_outline) — single agent, ~5-7d
  I  Phase 2.2 async regenerate — fork after H lands the worker handler
                pattern, ~2-3d
  J  Phase 2.3 per-stage rerun — fork at the same time as I, ~2d
  K  Phase 2.4 cancel — fork last (depends on H's cooperative-stop
                primitive if added), ~1-2d
  → I/J/K each add a new endpoint in api/routes.py and a new worker
    handler in task_worker. They do not touch schemas.py.
```

### 9.2 Critical path

`H` (Phase 2.1) is 5-7 days and cannot be subdivided usefully. Frontend
v2 outline editor is blocked until `H` ships.

To compress the calendar:

- Start `H` design work in parallel with Wave 0 (does not need any
  Wave 0 deliverable). The first 1-2 days of `H` are split-job design,
  which can happen on paper before any code lands.
- Do not assign `H` to the same agent that does Wave 1 — Wave 1 is also
  the highest-leverage task and overloading one agent serializes the
  plan.

### 9.3 Conflict mitigations (still applies after ownership transfer)

1. `schemas.py` block headers: when Wave 1 merges, the next contract
   change should add `# === <area> contract ===` anchors so future
   parallel work has stable insertion points.
2. `api/routes.py`: append-only for new endpoints. Do not reorder
   existing handlers in the same PR as adding new ones.
3. `pipeline.py`: Wave 2 G touches the run_stage timing wrapper.
   Wave 3 H touches the run_until_outline / run_after_outline split.
   These are different parts of the file and can coexist if both
   agents pull from the same base before opening PRs.
4. Each agent owns its own git worktree under
   `server/paper_agent/.claude/worktrees/<task-name>` (already the
   project's pattern per `MIGRATIONS.md`).
5. Tests are merge truth: every wave deliverable ships with new tests;
   `pytest server/paper_agent/tests/` must stay green at every wave
   boundary.

### 9.4 What NOT to parallelize

- **Wave 1 cannot be split across multiple agents.** One PR for all new
  Pydantic models. Splitting causes 3 schemas.py reviews and serial
  merges instead of one.
- **Phase 2.1 cannot be split across two implementation agents.** A
  state-machine design needs a single owner. A second agent writing
  integration tests in parallel is fine and recommended.
- **Frontend v2 cannot start before `H` lands.** v1.5 frontend can
  start after Wave 2; v2 outline editor is gated on `H`.

### 9.5 Headcount estimates

- 1 agent: ~5 weeks total (full serial within waves).
- 2 agents: ~3 weeks (Wave 0 parallel; Wave 2 parallel; Wave 3 partly
  parallel).
- 4 agents (recommended): ~2 weeks. Wave 0 finishes in half a day,
  Wave 1+2 in 3-4 days, Wave 3 fits in 6-7 days.
- 6+ agents: edge benefit decays; Wave 1 is single-agent by design.

---

## 10. Progress checklist (mirror of §3-§5 status)

Source-of-truth for "is the prep plan done yet?" — update this table as
PRs merge, not when work begins.

| Item | Status | Evidence (file:line or commit) | Notes |
|---|---|---|---|
| Pre-Phase 0 ownership transfer | 🟢 done (uncommitted) | `gateway/paper_generation/routes.py` reduced to 16-line proxy; `paper_agent/api/routes.py` owns router; new `tests/gateway_interface/` regression suite (~55+ tests) | Not yet committed; bundles refactor + tests in one stack |
| 0.1 Verify resolved citations | 🔲 pending | — | Needs Docker-enabled smoke run; can fork from Wave 0 |
| 0.2 Verify downloadable bundles | 🔲 pending | — | Should reuse `BundleValidationResult` |
| 1.1 Populate `validation_summary` | 🔲 pending | `api/routes.py:366` still `validation_summary=None` | Wave 2; depends on Wave 1 schema |
| 1.2 Stage timestamps | 🔲 pending | `pipeline.py` writes only run-level `finished_at`; per-stage `started_at` / `duration_ms` absent | Wave 2; depends on Wave 1 `PaperStageLogEntry` |
| 1.3 Manifest/artifact contract | 🔲 pending | `PaperManifest.artifact_index: dict[str, Any]` still loose | Wave 1 contract owner |
| 1.4 Outline + Figure schemas | 🔲 pending | No `OutlineDocument` / `FigureManifest` exported | Wave 1 contract owner |
| 1.5 Allowlist audit | 🟢 done | `tests/gateway_interface/test_storage.py:test_allowlist_decisions` parametrized over 16 ALLOW + 9 DENY cases, including PHI / inputs/idea.md / drafts/intro_rw_draft / drafts/snapshots / validation guard JSONs | — |
| 1.6 Single-template policy | 🟢 done | `api/routes.py:238-242` rejects `len != 1`; `tests/gateway_interface/test_routes.py:test_post_papers_rejects_empty_templates` (400) and `:test_post_papers_rejects_multiple_templates` (400 + "exactly one" detail) | — |
| 2.1 Outline approve gate | 🔲 pending | — | Critical path; split jobs design |
| 2.2 Async regenerate | 🔲 pending | `regenerate_paper_section` runs synchronously | Worker handler `paper_generation.regenerate_section` to be added |
| 2.3 Per-stage rerun | 🔲 pending | — | New endpoint + worker handler |
| 2.4 Cancel | 🔲 pending | — | Depends on cooperative cancel primitive |

Wave 0 status: **2/4 done** (1.5, 1.6). Remaining: 0.1, 0.2 verification smoke tests.
