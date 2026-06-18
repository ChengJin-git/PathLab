# PathScientist — External Validation Pipeline Remediation Plan

> Date: 2026-06-17
> Status: Implemented — external pytest subset verified on Python 3.10 fallback and Python 3.12 OpenHands SDK environments
> Branch: `fix-pathscientist-persist-web-sessions-work` (worktree `PathLab_fix_pathscientist_sessions`)
> Scope: the **external validation / external_test** pipeline only. A focused companion to
>   `docs/plan/2026-06-17-pathscientist-code-review-remediation-plan.md` (tasks here expand its `C-EXT`).
> Line numbers are against **this branch's working tree** (which differs from `pathscientistv0.1.0dev`:
>   `external_request.py` is +142 committed; `runner.py`/`run_experiment.py` have uncommitted WIP — see §4).

All paths are relative to `server/backend/pathscientist/` unless noted.

## 1. What the external pipeline does today (current map)

```
intake (LLM)            contract              plan insertion           dispatch                    execute
infer_external_request  normalize_external_   _with_external_test      _advance_execution_plan_    external_test.py
(external_request.py)    test_contract         (execution_plan.py)      after_metric_step           (templates/
  -> external_test_      (external_contract.py)  -> [extract_external_   (runner.py:797)             external_test_
     request in state.     role-tagged datasets    features?] +          -> fills MODEL_PATH from    template.py)
     grounding             + flat external_* keys   external_test step    best_run, records
                                                                          external_test_history
```
- Two intakes: explicit (`PATHSCIENTIST_EXTERNAL_TEST=1` + `_CONTRACT`, or `skill_name=external_test`) or **LLM natural-language inference** (`infer_external_request`, confidence ≥ medium gate).
- The external step runs **after** training (budget exhausted), evaluates a **fixed best-run model** on the external cohort, and is excluded from the ratchet improvement gate / iteration budget (`is_external_test_run`), landing in `external_test_history`.

## 2. Tasks

### EXT-1 · P0 · HIGH · `orchestrator/director.py:177-189` · effort M
**Problem:** the REVIEW→SYNTHESIS short-circuit is `if state.stop_reason or (iteration_index >= max_iterations and not pending_external_test)`. The `not pending_external_test` guard only protects the **budget** branch; **any** truthy `state.stop_reason` routes straight to synthesis **regardless of a queued external_test**. The runner sets `stop_reason="budget_exhausted"` in the same turn it advances to the external step (and stalls set `stop_reason` too), so a user-requested external validation is **silently dropped** whenever training trips a budget/stall stop. The final report is then presented as complete without the external cohort the user explicitly asked for.
**Fix:** only short-circuit to synthesis on a `pending_external_test` when the stop is a user decision, e.g.:
```python
pending_external_test = _current_execution_skill(state) == "external_test"
user_stop = state.stop_reason in {"user_cancelled", "approval_rejected"}
if (user_stop) or (not pending_external_test and (state.stop_reason or state.iteration_index >= state.max_iterations)):
    ... -> synthesis
else:
    ... -> execution   # budget_exhausted / stall_limit with a pending external_test continues into the external step
```
**Acceptance:** a session with a queued `external_test` step that hits `budget_exhausted` or `stall_limit` during training still runs the external step before synthesis; a `user_cancelled`/`approval_rejected` stop still goes straight to synthesis.
**Tests:** extend `tests/test_budget_stop_reason.py` (add a pending-external case) + a director unit test.
**Depends-on:** — **Owner:** ____

### EXT-2 · P1 · MEDIUM · `orchestrator/external_request.py:86-110` (+ missing calc `:463-483`) · effort S
**Problem:** `_normalize_task_type` returns the hardcoded default `"mil_classification"` when the LLM's `external_task_type`, the selected skill, and the task_profile are all unrecognized. That default then drives `_discover_contract_paths`' required-input computation, so a non-MIL external request (e.g. segmentation, phrased unexpectedly) is asked for `external_features_dir`/`external_splits_file` instead of `external_masks_dir`/`external_predictions_dir` — the contract's `missing`/`status` is computed against the wrong task.
**Fix:** return `""` (unknown) instead of guessing; in `infer_external_request`, when task_type is unknown, set `status="unknown_task_type"` and add `external_task_type` to `missing` (do not fabricate a contract). Only default when there is at least a weak positive signal (skill/profile).
**Acceptance:** a segmentation external request with an unrecognized `external_task_type` yields `status="unknown_task_type"` with `external_task_type` in `missing`, not a MIL contract.
**Tests:** `tests/test_external_request.py` (unknown task-type case).
**Depends-on:** — **Owner:** ____

### EXT-3 · P1 · MEDIUM · `orchestrator/external_request.py:159-164, 518-539` · effort S
**Problem:** `_parse_response` returns `{}` on any `extract_json` failure; `infer_external_request` then reads `external_validation_requested=False` and returns `status="not_requested"` — i.e. a transient LLM/parse failure is **indistinguishable from a genuine "no external validation requested"**, and the negative result is stored into `state.grounding["external_test_request"]` (runner.py:492) and effectively cached for the session. A user who asked for external validation can have it silently dropped by one bad parse.
**Fix:** when `raw_text` is non-empty but `_parse_response` yields `{}`, return `status="parse_error"` (distinct from `not_requested`); do not treat a parse failure as a negative. Consider one retry, and do not persist/cache a `parse_error`/`llm_error` as the final answer (let a later turn re-infer).
**Acceptance:** a malformed LLM response yields `status="parse_error"`, not `not_requested`; the request is re-attempted rather than silently dropped.
**Tests:** `tests/test_external_request.py` (unparseable-response case).
**Depends-on:** — **Owner:** ____

### EXT-4 · P0 · HIGH · `tools/run_experiment.py:498` → sink `runtime/workspace.py:175-180` · effort S
**Problem:** `_external_test_env` sets `PATHSCIENTIST_EXTERNAL_DATASETS = json.dumps(contract["datasets"])` — a value containing spaces, quotes, and braces. In **local (non-sandbox) mode**, `workspace.run_script` builds `cmd = f"{env_prefix}{runner} {script_path}"` joining env vars **unquoted** into a shell command, so this JSON value is the most reliable trigger of that shell breakage/injection (it virtually always contains spaces/quotes). External runs are where the K2/`A3` defect actually fires in practice.
**Fix:** the real fix is `A3` from the main plan — pass env through the subprocess `env=` dict (mirror the apptainer `APPTAINERENV_` branch) instead of string-formatting; until then, at minimum `shlex.quote` each value. This task is the external-pipeline driver/regression for that change.
**Acceptance:** an external_test run in `PATHSCIENTIST_SANDBOX=local` mode with a multi-dataset contract executes correctly; the JSON env value is never re-parsed by a shell.
**Tests:** `tests/test_local_run_env_quoting.py` with an `external_test` contract env.
**Depends-on:** main-plan `A3` (shared fix) **Owner:** ____ (coordinate with A3 owner)

### EXT-5 · P1 · MEDIUM · `tools/run_experiment.py:486-498` + `domain/templates/external_test_template.py:285-316` · effort M
**Problem:** external evaluation runs against the best-run model resolved from `model_source="best_run"` → `PATHSCIENTIST_MODEL_PATH` (filled from `last_experiment.model_path`). Two soft spots: (a) if `model_path` is empty/unresolved (model never saved, or wiped by `git clean -fd` — see main-plan `D-LOSS`), the external step can launch with no real checkpoint; (b) `_build_model` can fall back to `_FallbackLinearHead` when the MIL architecture can't be resolved from metadata. Today `load_state_dict` is strict (good — a shape mismatch raises), but the failure modes should be made explicit so an external "validation" can never report metrics from a not-actually-loaded model.
**Fix:** in the external dispatch, **refuse** to run external_test when `best_run` resolves to an empty/missing `model_path` (return an actionable error, not a run). In the template, keep `load_state_dict(..., strict=True)`, and assert the loaded architecture matches the recorded training architecture (from model metadata) before evaluating; never evaluate on a fallback/partially-initialized head.
**Acceptance:** external_test with an unresolved/empty model path fails fast with a clear message; a metadata/shape mismatch raises rather than producing metrics.
**Tests:** `tests/test_external_test_model_resolution.py`.
**Depends-on:** main-plan `D-LOSS` (so the model survives to be loaded) **Owner:** ____

### EXT-6 · P1 · MEDIUM · `tools/run_experiment.py` (external_test path), `tools/ratchet.py`, `synthesis/*` · effort M
**Problem:** external_test runs are intentionally excluded from the ratchet improvement gate and iteration budget, and recorded separately in `external_test_history`. Verify they are **not** also excluded from the integrity gates they *should* face: the synthetic-data check and the metrics-parse hard-gate (main-plan `C-GATE`) must still apply to an external result, and the report must clearly **label external metrics as external** (separate from internal val/test) so an external number is never presented as the internal headline metric, or vice-versa.
**Fix:** ensure the synthetic-data / metrics-parse gates run for `run_kind="external_test"`; in synthesis/report, render external_test_history under a distinct "External Validation" section with its own cohort/dataset name, never merged into the internal comparison table's best-metric.
**Acceptance:** a synthetic external result is rejected; the report shows external metrics in a clearly separated section tagged with the external dataset name.
**Tests:** extend `tests/test_report_builder*.py` and a synthetic-external case.
**Depends-on:** main-plan `C-GATE` **Owner:** ____

### EXT-7 · P1 · MEDIUM · resume × external (this branch's core) · `persistence/*`, `gateway/pathscientist_persistence.py`, `orchestrator/runner.py:767-779,1192` · effort M
**Problem:** the queued external_test lives in `state.grounding["external_test_request"]` and the `external_test` step in `state.execution_plan`. Because this branch adds **web session resume**, a session can be paused/resumed *before* the external step runs. Verify the resume path reconstructs both `grounding["external_test_request"]` and the pending `execution_plan` external step, so a resumed session actually **re-dispatches** the external validation instead of finishing without it. (The gateway persists `grounding` inside `experiment_plan`, but confirm it round-trips into the resumed `ResearchSessionState` and that `_advance_execution_plan_after_metric_step` still sees the pending step.)
**Fix:** add a resume integration test; if `grounding["external_test_request"]`/`execution_plan` is not restored, plumb it through the resume reconstruction (`persistence/resume.py` + state bridge) so a pending external_test survives a web pause/resume.
**Acceptance:** start a session that requests external validation, persist+resume before the external step, and confirm the resumed run executes the external_test and records `external_test_history`.
**Tests:** `tests/test_resume_pending_external_test.py` (or a gateway route test).
**Depends-on:** — (interacts with main-plan `A18`: resume must also re-register the workspace guard) **Owner:** ____

## 3. Suggested order
1. **EXT-1** (highest user-visible integrity loss — external silently dropped).
2. **EXT-4** alongside main-plan `A3` (external is the guaranteed trigger of the local-mode injection).
3. **EXT-2 / EXT-3** (intake correctness — small, independent).
4. **EXT-5 / EXT-6 / EXT-7** (model-resolution, integrity-labeling, resume — coordinate with `D-LOSS`/`C-GATE`/`A18`).

## 4. Branch-state notes (read before starting)
- This worktree has **uncommitted WIP** touching the exact files these tasks edit: `tools/run_experiment.py` (+198), `orchestrator/runner.py` (+62), plus `external_request.py` was already +142 vs dev. **Land or rebase that WIP first**, or coordinate so EXT-2/EXT-3/EXT-4 don't conflict.
- Good news already true on this branch: `external_test_template.py` `torch.load` uses `weights_only=True` (so main-plan `B-PICKLE` does **not** apply to the external template), and `load_state_dict` is strict.
- The branch is **2 commits ahead of** `origin/fix-pathscientist-persist-web-sessions`; push/sync before assigning so reviewers see the latest.

## 5. Tracking checklist

| ID | Pri | Sev | File (this branch) | Effort | Owner | Status |
|---|---|---|---|---|---|---|
| EXT-1 | P0 | High | director.py:177-189 | M | Codex | ☑ Implemented |
| EXT-2 | P1 | Med | external_request.py:86-110 | S | Codex | ☑ Implemented |
| EXT-3 | P1 | Med | external_request.py:159-164,518-539 | S | Codex | ☑ Implemented |
| EXT-4 | P0 | High | run_experiment.py:498 → workspace.py:175-180 | S | Codex | ☑ Implemented |
| EXT-5 | P1 | Med | run_experiment.py:486-498 + external_test_template.py:285-316 | M | Codex | ☑ Implemented |
| EXT-6 | P1 | Med | run_experiment.py (ext path) + synthesis/* | M | Codex | ☑ Implemented |
| EXT-7 | P1 | Med | resume + gateway persistence | M | Codex | ☑ Implemented |

## 6. Implementation notes

- EXT-1: `ResearchDirector` now allows a pending `external_test` to continue after `budget_exhausted` or `stall_limit`; explicit user stops still route to synthesis.
- EXT-2/EXT-3: external-request inference now distinguishes malformed LLM responses (`parse_error`) and unknown task types (`unknown_task_type`) from genuine `not_requested`; transient `parse_error`/`llm_error` results are returned to the caller but not cached over the session's existing external request.
- EXT-4: local `Workspace.run_script` shell-quotes env keys/values and script paths; regression covers JSON external dataset env values with quotes/spaces.
- EXT-5: `run_experiment` fails fast when `model_source="best_run"` has no resolvable checkpoint, and the external template refuses fallback patch heads.
- EXT-6: synthesis carries `external_test_history` into a separate "External Validation" report section; synthetic-data rejection remains active for `run_kind="external_test"`.
- EXT-7: resume preserves queued `external_test` execution plans, restores external-test runtime config from persisted state/step inputs, and keeps injected best-run `model_path`.

Verification snapshot:
- `PYTHONPATH=backend /tmp/pathlab_ext_test_venv/bin/python -m py_compile ...` succeeded for the touched external-validation modules and tests.
- Python 3.10 fallback environment (`/tmp/pathlab_ext_test_venv`, no OpenHands SDK): `PYTHONPATH=backend /tmp/pathlab_ext_test_venv/bin/python -m pytest backend/pathscientist/tests/test_external_request.py backend/pathscientist/tests/test_report_builder.py backend/pathscientist/tests/test_synthesis_external_validation.py backend/pathscientist/tests/test_resume_pending_external_test.py backend/pathscientist/tests/test_budget_stop_reason.py backend/pathscientist/tests/test_local_run_env_quoting.py backend/pathscientist/tests/test_external_test_model_resolution.py -q` passed: `30 passed`.
- Python 3.12 OpenHands SDK environment (`/tmp/pathlab_ext_py312_venv`, SDK installed from pinned repo commit): the same pytest subset passed: `30 passed, 1 warning`.
