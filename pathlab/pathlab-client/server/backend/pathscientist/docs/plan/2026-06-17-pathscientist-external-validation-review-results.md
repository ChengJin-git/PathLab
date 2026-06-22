# PathScientist — External Validation Implementation: Review Results

> Date: 2026-06-17
> Type: **REVIEW RESULT** (not a plan)
> Reviews: the external-validation implementation on branch `fix-pathscientist-persist-web-sessions-work`
>   (working-tree / uncommitted changes), against
>   [`2026-06-17-pathscientist-external-validation-remediation-plan.md`](2026-06-17-pathscientist-external-validation-remediation-plan.md).
> Reviewer: code review (full diff read + new tests read + targeted verification).
> Paths relative to `server/backend/pathscientist/`.

## Verdict

**Solid. EXT-1 … EXT-7 are all correctly implemented and backed by meaningful tests** (real `Workspace` +
session registry + `RunExperimentExecutor`, not pure mocks). Follow-up repairs addressed the actionable code issues
listed below; the remaining before-merge item is review-scope hygiene (split the unrelated PathLab registration/linkage
work).

### Scope reviewed
- Changed (uncommitted): `orchestrator/director.py`, `orchestrator/external_request.py`, `orchestrator/runner.py`,
  `tools/run_experiment.py`, `runtime/workspace.py`, `domain/templates/external_test_template.py`,
  `synthesis/context.py`, `synthesis/report_builder.py`.
- New tests: `tests/test_external_request.py`, `test_external_test_model_resolution.py`, `test_local_run_env_quoting.py`,
  `test_resume_pending_external_test.py`, `test_synthesis_external_validation.py`; modified `test_budget_stop_reason.py`.

## Per-task verdict

| Task | Implementation | Verdict |
|---|---|---|
| **EXT-1** director drops queued external on stop_reason | `director.py:177-189`: `user_stop = stop_reason in {user_cancelled, approval_rejected}`; routes to synthesis only on `user_stop` or `(not pending_external_test and (stop_reason or iteration_index>=max))`. budget/stall + pending_external → continues to EXECUTION. | ✅ correct |
| **EXT-2** unknown task_type defaulted to MIL | `external_request._normalize_task_type` → `return ""`; `infer_external_request` `if not task_type:` → `status="unknown_task_type"`, `enabled=False`, `contract={}`, adds `external_task_type` to `missing`. | ✅ |
| **EXT-3** parse failure → silent not_requested | `_parse_response` returns `None` for empty/unparseable/non-dict; `data is None` → `status="parse_error"`. Runner `_apply_external_request_inference` stores it under `external_test_request_last_error` and **early-returns without overwriting** `external_test_request`. | ✅ negative not cached |
| **EXT-4** local-mode shell injection | `workspace.run_script` local branch now passes a command list and environment through `subprocess.run(..., env=...)`, so external JSON contract values are not re-parsed by a shell. | ✅ injection closed |
| **EXT-5** external runs against an unresolved model / fallback head | `run_experiment._external_test_model_resolution_error`: fail-fast (`exit_code=-1`, before `run_script`) when a required `PATHSCIENTIST_MODEL_PATH` is empty / missing / not-a-file, including explicit `model_path` sources. `external_test_template.build_patch_classification_model` now `raise`s instead of returning a fallback head; `load_state_dict` is strict. | ✅ |
| **EXT-6** external metrics integrity + separate report section | Synthetic-data gate confirmed to fire on external runs (`test_external_test_rejects_synthetic_metrics`); `synthesis/context.py` exposes `external_test_history`; `report_builder._build_external_validation_content` renders a distinct "External Validation" section labelled "reported separately from internal". | ✅ |
| **EXT-7** resume re-dispatches pending external_test | `runner._has_resumable_execution_step` + `_sync_external_test_config_from_state` restore `external_test_enabled/contract` from persisted `state.grounding["external_test_request"]` / plan step inputs on resume, then re-dispatch the current step. | ✅ |

Test coverage is genuine: parse_error / no-cache / unknown_task_type / known-skill-supplies-task_type; model_path
empty / missing-on-disk; synthetic rejection; patch fallback refusal.

## Issues to address (ranked)

### 🟡 MEDIUM — async DB uses `asyncio.run()` (in the bundled, unrelated registration code) — FIXED
`runner._run_async_best_effort` (`runner.py:~50-58`): if a loop is running it **skips**; otherwise it calls
`asyncio.run(coro)` — a **fresh event loop** — to run `safe_session()` async DB work. But the gateway's SQLAlchemy
async engine is typically bound to the gateway loop (the persistence module deliberately uses
`run_coroutine_threadsafe` for exactly this reason). Consequences:
- gateway async context → registration is **skipped** outright;
- worker thread + new loop + shared engine → likely `Future attached to a different loop`, swallowed as a best-effort warning.

Net: **PathLab dataset registration likely never runs in the web/gateway path** (where it matters most).
**Fix:** mirror the persistence module — schedule on the configured gateway loop via `run_coroutine_threadsafe`,
not `asyncio.run`. *(This belongs to `_register_acquired_dataset_with_pathlab`, not to external itself — see next item.)*

**Repair status:** `_run_async_best_effort` now uses the configured `gateway.pathscientist_persistence._gateway_loop`,
uses `run_coroutine_threadsafe` from worker threads, schedules directly when already on the gateway loop, and only falls
back to `asyncio.run()` when no loop is running and no gateway loop is configured. Regression coverage:
`test_run_async_best_effort_uses_configured_gateway_loop_from_worker_thread` and
`test_run_async_best_effort_schedules_when_already_on_gateway_loop`.

### 🟡 MEDIUM — scope: external work bundled with PathLab dataset registration/linkage
The diff mixes EXT-1…7 with a large unrelated feature: `_register_acquired_dataset_with_pathlab` +
`_run_async_best_effort` (`runner.py`), `_pathlab_linkage_for_run` (~150 lines in `run_experiment.py`), and the new
`dataset/pathlab_registration.py`. **Split into two commits/PRs** ("external validation hardening" vs "pathlab dataset
registration/linkage") for reviewability and clean rollback.

**Repair status:** not committed from this dirty worktree. The worktree contains additional unrelated WIP outside
PathScientist external validation (gateway RAG, frontend session UI, route tests, PDF assets), and the two features are
interleaved inside `orchestrator/runner.py` and `tools/run_experiment.py`. Do the split at staging/commit time with the
map below; do not create one broad commit from the current worktree.

Suggested split:

**Commit/PR A — external validation hardening**
- `backend/pathscientist/orchestrator/director.py`: pending external-test flow after budget/stall stops.
- `backend/pathscientist/orchestrator/external_request.py`: parse-error / unknown-task handling and request inference.
- `backend/pathscientist/runtime/workspace.py`: `run_script(..., env=...)` shell-escape fix and explicit SDK-fallback test flag.
- `backend/pathscientist/domain/templates/external_test_template.py`: remove fallback patch head / fail closed on missing architecture.
- `backend/pathscientist/synthesis/context.py`: expose `external_test_history`.
- `backend/pathscientist/synthesis/report_builder.py`: separate External Validation section, prefixed metric resolution, markdown escaping.
- `backend/pathscientist/tools/run_experiment.py`: external-test contract env, explicit model-path validation, external-history recording,
  synthetic/metrics gates. Exclude `_PATHLAB_UPLOADS_CHILD_DIRS`, `_pathlab_*` linkage helpers, and `last_experiment["pathlab"]` hunks.
- Tests: `test_external_request.py`, `test_external_test_model_resolution.py`, `test_local_run_env_quoting.py`,
  `test_resume_pending_external_test.py`, `test_synthesis_external_validation.py`, external-related hunks in
  `test_budget_stop_reason.py` and `test_report_builder.py`.
- Docs: `2026-06-17-pathscientist-external-validation-remediation-plan.md`,
  `2026-06-17-pathscientist-external-validation-review-results.md`.

**Commit/PR B — PathLab dataset registration/linkage**
- `backend/pathscientist/dataset/pathlab_registration.py`.
- `backend/pathscientist/orchestrator/runner.py`: `_pathscientist_persistence_module`, `_run_async_best_effort`,
  `_register_acquired_dataset_with_pathlab`, and acquisition-stage `pathlab_registration` attachment.
- `backend/pathscientist/tools/run_experiment.py`: `_PATHLAB_UPLOADS_CHILD_DIRS`, `_clean_path`, `_relative_to`,
  `_configured_pathlab_uploads_dir`, `_infer_pathlab_uploads_dir`, `_pathlab_child_path`, `_pathlab_training_link`,
  `_pathlab_features_dir`, `_pathlab_linkage_for_run`, `_pathlab_linkage_for_run_for_test`, and
  `last_experiment["pathlab"]` / `pathlab_training_task_id` hunks.
- Tests: `test_pathlab_dataset_registration.py`, PathLab-registration hunks in `test_dataset_acquisition_e2e.py`,
  PathLab-linkage hunks in `test_run_experiment_hf_token.py`.

Files requiring hunk-level staging (`git add -p` or equivalent): `backend/pathscientist/orchestrator/runner.py`,
`backend/pathscientist/tools/run_experiment.py`, `backend/pathscientist/tests/test_dataset_acquisition_e2e.py`,
`backend/pathscientist/tests/test_run_experiment_hf_token.py`.

### 🟢 LOW — EXT-4 used `shlex.quote` instead of the `env=` dict — FIXED
Closes the injection, but the local branch still (a) runs unsandboxed on the host (that is A2, separate) and
(b) builds a shell string. Passing env via the subprocess `env=` dict is cleaner and avoids quoting edge cases.
Also quoting the env **key** (`shlex.quote(str(k))=…`) is unusual — a no-op for normal names, but would break the
`K=V` assignment if a key ever contained a quoted char (env keys are controlled, so acceptable today).

**Repair status:** local `Workspace.run_script` now calls `subprocess.run(cmd, cwd=..., env=...)` with `cmd` as a list.
`test_run_script_passes_env_without_shell_reparsing` covers JSON/quote-heavy env values.

### 🟢 LOW — test-only SDK shim leaked into the production import path — FIXED
`workspace.py` now wraps the OpenHands import in `try/except ModuleNotFoundError` and adds `_SubprocessWorkspace`
(uses `subprocess.run(shell=True)`) + `_FallbackCommandResult`/`CommandResult` global juggling, to let the new unit
tests import the package without the full SDK. Only triggered when the SDK import fails (won't happen in prod), but it
is a production code branch. Prefer isolating the fallback to tests or gating it behind an explicit test flag.

**Repair status:** `_SubprocessWorkspace` is now gated behind
`PATHSCIENTIST_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK=1`; without the OpenHands SDK and without that explicit test flag,
`Workspace(...)` fails closed with a clear runtime error. Regression coverage:
`test_workspace_sdk_fallback_requires_explicit_test_flag`.

### 🟢 LOW — dead code — FIXED
`external_test_template.py:38` `_FallbackLinearHead` is now never returned (its only use became a `raise`). Delete it
to prevent re-introduction.

### 🟢 LOW — EXT-5 only gates `best_run` — FIXED
`_external_test_model_resolution_error` checks existence only when `model_source=="best_run"`. An explicitly supplied
`model_path` (other `model_source`) is not existence-checked. Cheap to also validate.

**Repair status:** `_external_test_model_resolution_error` now validates any non-empty resolved `PATHSCIENTIST_MODEL_PATH`,
including explicit model sources. Regression coverage:
`test_external_test_refuses_explicit_model_path_when_missing_on_disk`.

### 🟢 NIT — EXT-6 report rendering — FIXED
`_build_external_validation_content` reads the metric via `metrics.get(metric)` / `metrics["external"][metric]`; a value
stored under `test_auc`/`external_auc` renders blank — consider reusing `resolve_primary_metric`. Dataset names are
interpolated raw into a markdown table, so a name containing `|` breaks the table (external dataset names can originate
from the LLM — escape for safety; low risk, cosmetic).

**Repair status:** external report rendering now resolves prefixed metric names such as `external_auc` and `test_auc`
and escapes markdown table cells for run ID, dataset, task, and status. Regression coverage:
`test_external_validation_resolves_prefixed_metric_and_escapes_table_cells`.

## Strengths (preserve)
- Clean fail-fast pattern in `run_experiment` (returns a structured `is_error` observation *before* `run_script`).
- Tests use a real workspace + registry + executor and assert behaviour (no-run-on-refusal, synthetic rejection),
  not just function returns.
- EXT-3 correctly distinguishes a transient parse error from a genuine "not requested" and avoids caching the negative.
- EXT-1 logic is exactly right (user-stop vs budget/stall-with-pending-external).

## Before-merge checklist
- [x] Re-point `_run_async_best_effort` DB calls at the configured gateway loop (else registration is a no-op on web).
- [x] Replace local `Workspace.run_script` shell env-prefix execution with `subprocess.run(..., env=...)`.
- [x] Validate explicit external `model_path` sources, not only `best_run`.
- [x] Resolve `test_auc`/`external_auc`-style external report metrics and escape markdown table cells.
- [ ] Split external vs pathlab-registration into separate commits/PRs using the split map above.
- [x] Delete the now-dead `_FallbackLinearHead`.
- [x] Gate the `_SubprocessWorkspace` SDK-fallback behind an explicit test flag.
- [x] Run:
      `pytest backend/pathscientist/tests/test_external_request.py \
        backend/pathscientist/tests/test_external_test_model_resolution.py \
        backend/pathscientist/tests/test_local_run_env_quoting.py \
        backend/pathscientist/tests/test_resume_pending_external_test.py \
        backend/pathscientist/tests/test_synthesis_external_validation.py \
        backend/pathscientist/tests/test_budget_stop_reason.py -q`

Verification after follow-up repair:
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend /tmp/pathlab_review_test_venv/bin/python -m pytest backend/pathscientist/tests/test_dataset_acquisition_e2e.py::test_run_async_best_effort_uses_configured_gateway_loop_from_worker_thread backend/pathscientist/tests/test_dataset_acquisition_e2e.py::test_run_async_best_effort_schedules_when_already_on_gateway_loop backend/pathscientist/tests/test_external_test_model_resolution.py::test_external_test_refuses_explicit_model_path_when_missing_on_disk backend/pathscientist/tests/test_report_builder.py::test_external_validation_resolves_prefixed_metric_and_escapes_table_cells backend/pathscientist/tests/test_local_run_env_quoting.py -q` → `6 passed`.
- `PATHSCIENTIST_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend /tmp/pathlab_review_test_venv/bin/python -m pytest backend/pathscientist/tests/test_external_request.py backend/pathscientist/tests/test_external_test_model_resolution.py backend/pathscientist/tests/test_local_run_env_quoting.py backend/pathscientist/tests/test_resume_pending_external_test.py backend/pathscientist/tests/test_synthesis_external_validation.py backend/pathscientist/tests/test_budget_stop_reason.py -q` → `22 passed, 1 skipped`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend /tmp/pathlab_review_test_venv/bin/python -m pytest backend/pathscientist/tests/test_report_builder.py -q` → `11 passed`.
- `PYTHONDONTWRITEBYTECODE=1 /tmp/pathlab_review_test_venv/bin/python -m py_compile backend/pathscientist/orchestrator/runner.py backend/pathscientist/tools/run_experiment.py backend/pathscientist/synthesis/report_builder.py backend/pathscientist/domain/templates/external_test_template.py backend/pathscientist/runtime/workspace.py backend/pathscientist/tests/test_dataset_acquisition_e2e.py backend/pathscientist/tests/test_external_test_model_resolution.py backend/pathscientist/tests/test_report_builder.py backend/pathscientist/tests/test_local_run_env_quoting.py` → exit 0.
