"""Ratchet tools — git commit improvements / revert failures."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Self
from uuid import uuid4

from pydantic import Field

from openhands.sdk.llm import TextContent
from openhands.sdk.event import ObservationEvent
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

from ..runtime.data_protocol import (
    data_protocol_change_message as _data_protocol_change_message,
    extract_data_protocol as _extract_data_protocol,
    locked_data_protocol_from_tracker as _locked_data_protocol_from_tracker,
)

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ..runtime.workspace import Workspace

logger = logging.getLogger(__name__)


def _collect_recent_terminal_logs(conversation, limit: int = 6) -> list[str]:
    logs: list[str] = []
    if conversation is None:
        return logs

    for event in reversed(list(conversation.state.events)):
        if not isinstance(event, ObservationEvent) or event.tool_name != "terminal":
            continue
        text = getattr(event.observation, "text", "").strip()
        if not text:
            continue
        logs.append(text)
        if len(logs) >= limit:
            break
    return logs


def _resolve_finalization_metrics(session_id: str, metrics: dict) -> dict:
    if not session_id:
        return dict(metrics or {})

    try:
        from ..runtime.metric_parser import build_llm_metric_parser, recover_metrics_from_logs
        from ..runtime.session_registry import get_session
        from ..orchestrator.metrics_utils import resolve_primary_metric
    except Exception:
        return dict(metrics or {})

    try:
        deps = get_session(session_id)
    except KeyError:
        return dict(metrics or {})

    primary_metric = deps.config.primary_metric if deps.config else "auc"
    merged = dict(metrics or {})

    if deps.last_experiment and isinstance(deps.last_experiment.get("metrics"), dict):
        for key, value in deps.last_experiment["metrics"].items():
            merged.setdefault(key, value)

    if resolve_primary_metric(merged, primary_metric) > 0:
        return merged

    log_texts: list[str] = []
    if deps.last_experiment:
        log_texts.extend(
            text for text in (
                deps.last_experiment.get("stdout", ""),
                deps.last_experiment.get("stderr", ""),
            )
            if text
        )
    log_texts.extend(_collect_recent_terminal_logs(deps.conversation))

    llm_parser = build_llm_metric_parser(deps.config)
    return recover_metrics_from_logs(
        current_metrics=merged,
        primary_metric=primary_metric,
        log_texts=log_texts,
        llm_parser=llm_parser,
    )


def _finalize_iteration(
    session_id: str,
    metrics: dict,
    committed: bool,
    action_external: bool = False,
) -> None:
    """Update tracker and iteration state after a commit or revert.

    This is the single canonical finalization path — both ratchet_commit
    and ratchet_revert call it so orchestrator sees consistent state.

    ``action_external`` is forwarded from ``RatchetCommitAction.external`` /
    ``RatchetRevertAction.external``. When True and ``deps.last_experiment``
    is None, the evidence skip reason is tagged as
    ``"external_experiment_opt_in"`` (warning-severity in the IntegrityGuard)
    rather than ``"no_last_experiment"`` (fatal) — distinguishing a deliberate
    out-of-band experiment from a silent policy bypass.
    """
    if not session_id:
        return
    try:
        from ..runtime.session_registry import get_session
        deps = get_session(session_id)
        resolved_metrics = _resolve_finalization_metrics(session_id, metrics)

        # Plan-2026-04-29 P0 #3: a failed/timeout run must NOT promote
        # val_<metric> into primary <metric> via resolve_primary_metric's
        # fallback chain (test_ → val_ → best_val_). Pre-fix,
        # session_7a23f8edcce9 run_e568e217 had exit_code=-1 and only
        # val_auc=0.8424 in metrics; the tracker recorded auc=0.8424,
        # which polluted run_history and the comparison table.
        is_failed_run = bool(
            deps.last_experiment and (
                deps.last_experiment.get("exit_code", 0) != 0
                or deps.last_experiment.get("error_type", "")
            )
        )
        if is_failed_run and resolved_metrics:
            primary_name = (
                deps.config.primary_metric if deps.config else "auc"
            )
            # Move any direct primary-metric value into ``partial_metrics``
            # alongside val_/best_/test_ prefixed keys, then strip the
            # primary key from the top-level dict so resolve_primary_metric
            # sees no positive primary value for the failed run.
            partial: dict = {}
            cleaned: dict = {}
            for k, v in resolved_metrics.items():
                if k == primary_name or k.startswith(("val_", "best_val_", "best_")):
                    partial[k] = v
                else:
                    cleaned[k] = v
            # Keep a partial_metrics block for diagnostics so the agent /
            # synthesis can still show val_auc on the failed-run row.
            if partial:
                cleaned.setdefault("partial_metrics", partial)
            resolved_metrics = cleaned

        # Capture pre-increment iteration index — this is the canonical iteration number
        # for tracker, evidence, and orchestrator to all use consistently
        pre_increment_iteration = deps.iteration_state.iteration_index if deps.iteration_state else (deps.tracker.iteration if deps.tracker else 0)

        # Canonical run_id for this finalization — ensure_run_id() auto-generates
        # one if the agent reached this path without running run_experiment,
        # so tracker history, iteration state, and evidence all share a single
        # traceable identifier.
        #
        # Both branches return the canonical ``run_[0-9a-f]{8}`` shape
        # (Fix 5). The bare-uuid fallback only fires when iteration_state
        # itself is absent — extremely rare — but still produces a prefixed
        # id so downstream verifier checks stay consistent.
        if deps.iteration_state:
            run_id = deps.iteration_state.ensure_run_id()
        else:
            run_id = f"run_{uuid4().hex[:8]}"

        try:
            from ..orchestrator.metrics_utils import (
                is_external_test_run,
                is_non_metric_setup_run,
            )

            primary_name = deps.config.primary_metric if deps.config else "auc"
            exp = deps.last_experiment or {}
            external_test_run = is_external_test_run(
                run_kind=str(exp.get("run_kind", "") or "")
            )
            non_metric_setup = is_non_metric_setup_run(
                resolved_metrics,
                primary_name,
                run_kind=str(exp.get("run_kind", "") or ""),
                exit_code=int(exp.get("exit_code", 0) or 0),
                error_type=str(exp.get("error_type", "") or ""),
            )
        except Exception:
            external_test_run = False
            non_metric_setup = False

        if external_test_run:
            exp = deps.last_experiment or {}
            metrics_for_external = dict(resolved_metrics or {})
            failed_external = (
                not bool(committed)
                or bool(metrics_for_external.get("error"))
                or bool(metrics_for_external.get("quick_check_failed"))
                or int(exp.get("exit_code", 0) or 0) != 0
                or bool(exp.get("is_error"))
            )
            deps.external_test_history.append({
                "run_id": run_id,
                "metrics": metrics_for_external,
                "committed": bool(committed),
                "model_path": str(exp.get("model_path") or ""),
                "run_dir": str(exp.get("run_dir") or ""),
                "status": "failed" if failed_external else "completed",
            })

        # Update tracker only for metric-bearing scientific iterations.
        # Feature extraction/data setup may still be committed and evidenced,
        # but it must not spend the training iteration budget or create a
        # tracker row with missing AUC.
        if deps.tracker and not non_metric_setup and not external_test_run:
            deps.tracker.record(
                resolved_metrics,
                committed=committed,
                iteration=pre_increment_iteration,
                run_id=run_id,
            )
            if deps.last_experiment and deps.tracker.history:
                exp = deps.last_experiment
                metadata_keys = (
                    "run_dir",
                    "data_output_dir",
                    "data_output_artifacts",
                    "model_path",
                    "pathlab",
                    "quick_check",
                    "run_kind",
                    "error_type",
                )
                tracker_entry = deps.tracker.history[-1]
                for key in metadata_keys:
                    value = exp.get(key)
                    if value not in (None, "", [], {}):
                        tracker_entry[key] = value

        # Update iteration state (increments iteration_index).
        # Append to finalized_run_ids BEFORE record_iteration so the canonical
        # list stays consistent with the tracker entry we just wrote. Setup
        # runs deliberately skip this block so remaining_budget is unchanged.
        if deps.iteration_state:
            if not non_metric_setup and not external_test_run:
                deps.iteration_state.finalized_run_ids.append(run_id)
                deps.iteration_state.record_iteration(
                    metrics=resolved_metrics,
                    committed=committed,
                )
            # Reset last_run_id so the next iteration's ensure_run_id() mints
            # a fresh uuid instead of reusing this one. Prevents the sticky
            # run_id bug (session_b14b074d2268) where finalized_run_ids
            # collapsed 17 distinct iterations onto a single id because
            # ensure_run_id() is idempotent when last_run_id is already set.
            deps.iteration_state.last_run_id = ""

        # Persist to agent_state if conversation is available
        if deps.conversation:
            from ..persistence.state_bridge import (
                dump_iteration_state,
                dump_tracker_state,
                update_agent_state,
            )
            update_agent_state(
                deps.conversation,
                tracker_state=dump_tracker_state(deps.tracker),
                iteration_state=dump_iteration_state(deps.iteration_state),
            )

        # Collect evidence if last_experiment is available. Every failure
        # mode — no last_experiment, no workspace, underlying store exception
        # — lands as a structured entry on ``deps.evidence_skipped_runs`` so
        # the IntegrityGuard can flag committed runs whose evidence is missing
        # with an actionable reason instead of silently warning to the log.
        from ..evidence.collector import EvidenceCollector, EvidenceFinalizeResult
        from ..evidence.store import EvidenceStore

        result: EvidenceFinalizeResult | None = None
        if deps.last_experiment and deps.workspace:
            try:
                evidence_dir = deps.workspace.root / ".evidence"
                store = EvidenceStore(evidence_dir)
                collector = EvidenceCollector(
                    workspace_root=deps.workspace.root,
                    store=store,
                    session_id=session_id,
                    primary_metric=deps.config.primary_metric if deps.config else "auc",
                )
                exp = dict(deps.last_experiment)  # copy so pop doesn't mutate
                # Use ratchet metrics if provided (revert passes actual run metrics)
                if resolved_metrics:
                    exp["metrics"] = resolved_metrics
                # Ensure evidence uses the same canonical run_id as tracker /
                # finalized_run_ids. last_experiment may have a blank run_id if
                # the agent committed without running run_experiment.
                if not exp.get("run_id"):
                    exp["run_id"] = run_id
                collector.record_experiment_output(**{
                    k: exp.get(k, v) for k, v in {
                        "run_id": "",
                        "run_dir": "",
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": "",
                        "metrics": {},
                        "duration": 0.0,
                        "started_at": "",
                        "data_output_dir": "",
                        "data_output_artifacts": None,
                        "model_path": "",
                        "pathlab": {},
                        "quick_check": False,
                        "run_kind": "",
                    }.items()
                })
                # Forward pre-revert snapshots if present
                if "_pre_revert_code" in exp:
                    collector._experiment["_pre_revert_code"] = exp["_pre_revert_code"]
                if "_pre_revert_diff" in exp:
                    collector._experiment["_pre_revert_diff"] = exp["_pre_revert_diff"]
                if "_pre_revert_untracked" in exp:
                    collector._experiment["_pre_revert_untracked"] = exp["_pre_revert_untracked"]
                result = collector.finalize(
                    committed=committed, iteration=pre_increment_iteration
                )
            except Exception as e:
                result = EvidenceFinalizeResult(
                    skipped=True,
                    skipped_reason=f"exception:{type(e).__name__}:{e}",
                )
                logger.exception("Evidence collection raised")
        elif not deps.last_experiment:
            # Distinguish deliberate external-opt-in from silent policy bypass
            # so the IntegrityGuard can downgrade the former to a warning.
            # action_external is threaded from RatchetCommit/RevertAction.external;
            # when True, the missing evidence is a known trade-off, not a defect.
            skip_reason = (
                "external_experiment_opt_in"
                if action_external
                else "no_last_experiment"
            )
            result = EvidenceFinalizeResult(
                skipped=True, skipped_reason=skip_reason
            )
        elif not deps.workspace:
            result = EvidenceFinalizeResult(
                skipped=True, skipped_reason="no_workspace"
            )

        if result and result.skipped:
            deps.evidence_skipped_runs.append(
                {"run_id": run_id, "reason": result.skipped_reason}
            )

        # Plan T2: persist evidence as a tracked metadata commit so a later
        # ratchet_revert (which calls `git clean -fd`) cannot wipe a
        # committed run's evidence record. This was the session_a70dd3a564c1
        # failure mode — evidence was on disk but untracked, then deleted on
        # the next failed iteration's revert, leaving evidence_run_missing
        # as the canonical state for a run that actually succeeded.
        #
        # Use commit_paths (NOT commit) so we don't sweep an unrelated dirty
        # train.py from a follow-up iteration into the metadata commit.
        if (
            result
            and not result.skipped
            and result.record_path
            and deps.workspace
        ):
            commit_paths = getattr(deps.workspace, "commit_paths", None)
            if callable(commit_paths):
                try:
                    commit_paths(
                        [".evidence"],
                        f"evidence: record {run_id}",
                    )
                except Exception as e:
                    # Don't fail the whole ratchet on metadata-commit failure;
                    # surface it to the integrity guard instead.
                    deps.evidence_skipped_runs.append({
                        "run_id": run_id,
                        "reason": f"evidence_commit_failed:{type(e).__name__}:{e}",
                    })
                    logger.exception("Evidence metadata commit failed")
            else:
                logger.debug(
                    "Workspace has no commit_paths(); evidence record left uncommitted"
                )

        deps.last_experiment = None  # clear whether collected or skipped
    except (KeyError, AttributeError):
        pass


# --- Commit ---

class RatchetCommitAction(Action):
    message: str = Field(description="Commit message describing the improvement.")
    metrics: dict = Field(default_factory=dict, description="Metrics to record with the commit.")
    external: bool = Field(
        default=False,
        description=(
            "Set to true ONLY when the experiment was run outside the "
            "RunExperimentTool (e.g. a long-running job launched on a "
            "different machine). The evidence record will be marked "
            "'external_experiment_opt_in' and the integrity guard will "
            "downgrade the missing-evidence fatal to a warning."
        ),
    )


class RatchetCommitObservation(Observation):
    commit_hash: str = Field(default="", description="Git commit hash.")
    files: list[str] = Field(default_factory=list, description="Files in workspace.")


class RatchetCommitExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace, session_id: str = ""):
        self._workspace = workspace
        self._session_id = session_id

    def __call__(
        self,
        action: RatchetCommitAction,
        conversation: "LocalConversation | None" = None,
    ) -> RatchetCommitObservation:
        from ..runtime.workspace import CommitFailed

        # Resolve deps once so all gates read from the same snapshot.
        deps = None
        if self._session_id:
            try:
                from ..runtime.session_registry import get_session
                deps = get_session(self._session_id)
            except KeyError:
                deps = None  # session registry lost — fall through

        # Gate A (2026-04-22 session 8e48c15d38cb review, Finding 2):
        # refuse commits on quick_check runs. quick_check runs use a
        # reduced epoch budget (2 epochs) and are intended for sanity-
        # checking, not for scientific results. The reviewed session
        # committed a 2-epoch "0.8643" as best-ever when the corresponding
        # 50-epoch full run only reached 0.8436.
        if (
            not action.external
            and deps is not None
            and deps.last_experiment
            and deps.last_experiment.get("quick_check")
        ):
            return RatchetCommitObservation(
                commit_hash="",
                files=self._workspace.list_files(),
                content=[TextContent(text=(
                    "❌ ratchet_commit refused: last_experiment was a quick_check run.\n"
                    "  quick_check runs use a reduced epoch budget and are intended for\n"
                    "  sanity-checking, not for committing scientific results. Re-run\n"
                    "  the same configuration through run_experiment with quick_check=false\n"
                    "  to capture real metrics, then retry ratchet_commit."
                ))],
            )

        # Gate B (2026-04-22 session 8e48c15d38cb review, Finding 3):
        # refuse commits on runs that did not complete cleanly. A non-zero
        # exit_code or non-empty error_type means the agent should be calling
        # ratchet_revert, not ratchet_commit. The reviewed session committed
        # run_f32a1b74 despite exit_code=-1 / error_type="Unknown".
        if (
            not action.external
            and deps is not None
            and deps.last_experiment
        ):
            exit_code = deps.last_experiment.get("exit_code", 0)
            error_type = deps.last_experiment.get("error_type", "") or ""
            if exit_code != 0 or error_type:
                return RatchetCommitObservation(
                    commit_hash="",
                    files=self._workspace.list_files(),
                    content=[TextContent(text=(
                        f"❌ ratchet_commit refused: last_experiment did not complete cleanly.\n"
                        f"  exit_code = {exit_code}  error_type = {error_type!r}\n"
                        f"  Runs that failed or produced errors should be reverted with\n"
                        f"  ratchet_revert, not committed. Use ratchet_revert to restore\n"
                        f"  the previous workspace state."
                    ))],
                )

        # Gate: refuse commits that were not preceded by run_experiment,
        # unless the caller explicitly opted into external mode.
        #
        # Motivating defect: session_b14b074d2268 (2026-04-20) had 11
        # committed runs whose evidence records all carried
        # reason="no_last_experiment" because the agent had called
        # `terminal` + `python train.py` + `ratchet_commit` directly,
        # skipping RunExperimentTool and leaving `deps.last_experiment`
        # unset. The gate refuses that shape at the tool boundary so the
        # evidence store can't be silently bypassed.
        if not action.external and deps is not None:
            if deps.last_experiment is None:
                return RatchetCommitObservation(
                    commit_hash="",
                    files=self._workspace.list_files(),
                    content=[TextContent(text=(
                        "❌ ratchet_commit requires a preceding run_experiment.\n"
                        "  Run the experiment through the run_experiment tool so "
                        "metrics, artifacts, stdout, stderr, and code state are "
                        "captured in the evidence store. Then retry ratchet_commit."
                    ))],
                )

            # Stale last_experiment gate (Fix A, 2026-04-21 post-fix review):
            # refuse if last_experiment["run_id"] is present but differs from
            # iteration_state.last_run_id. Without this check the evidence
            # collector would snapshot the older run against the newer
            # tracker run_id, splitting lineage. The canonical repro in the
            # review: last_experiment.run_id = "run_old1111",
            # iteration_state.last_run_id = "run_new2222" — tracker records
            # the new id, evidence lands under the old id.
            # When either side is blank we skip the match check (legacy
            # entries pre-dating Fix 1 may have no run_id; blank
            # iteration_state.last_run_id just means run_experiment hasn't
            # set it yet for this iteration).
            exp_run_id = deps.last_experiment.get("run_id", "")
            current_run_id = (
                deps.iteration_state.last_run_id if deps.iteration_state else ""
            )
            if exp_run_id and current_run_id and exp_run_id != current_run_id:
                return RatchetCommitObservation(
                    commit_hash="",
                    files=self._workspace.list_files(),
                    content=[TextContent(text=(
                        f"❌ ratchet_commit refused: last_experiment is stale.\n"
                        f"  last_experiment.run_id = {exp_run_id!r}\n"
                        f"  iteration_state.last_run_id = {current_run_id!r}\n"
                        f"  The evidence collector would snapshot the older run against\n"
                        f"  the newer tracker run_id, splitting lineage. Run the current\n"
                        f"  experiment through run_experiment before committing."
                    ))],
                )

        # Gate C (2026-04-22 session 8e48c15d38cb review, Findings 1 & 6):
        # resolve authoritative metrics from the on-disk artifact
        # (deps.last_experiment["metrics"]) instead of the LLM-supplied
        # action.metrics. The LLM may remember stale quick_check numbers
        # or copy-paste incorrect values across commits — action.metrics
        # cannot be trusted as the source of truth for tracker state.
        #
        # If the artifact has metrics we use them; otherwise we fall back
        # to action.metrics (same behavior as before this fix). The commit
        # message itself can still carry action.metrics as free-form LLM
        # annotation — only the tracker / iteration-state path is hardened.
        artifact_metrics: dict = {}
        if (
            deps is not None
            and deps.last_experiment
            and isinstance(deps.last_experiment.get("metrics"), dict)
        ):
            artifact_metrics = dict(deps.last_experiment["metrics"])
        commit_metrics_source = artifact_metrics or dict(action.metrics or {})

        # Gate: synthetic/mock/demo fallback metrics are not scientific
        # evidence. Even a clean exit_code must fail closed here because old
        # sessions could generate fake Virchow-shaped features and report a
        # formal AUC without touching real data.
        try:
            from ..orchestrator.metrics_utils import is_invalid_synthetic_run
            synthetic_metrics = is_invalid_synthetic_run(commit_metrics_source)
        except Exception:
            synthetic_metrics = False
        if synthetic_metrics:
            return RatchetCommitObservation(
                commit_hash="",
                files=self._workspace.list_files(),
                content=[TextContent(text=(
                    "❌ ratchet_commit refused: metrics indicate synthetic/mock/demo data.\n"
                    "  Synthetic fallback runs are not valid scientific evidence and "
                    "must not be committed as improvements.\n"
                    "  Use real data: fix DATA_DIR/FEATURES_DIR/LABELS paths, run "
                    "dataset acquisition/readiness, or fail with a data-readiness "
                    "error instead of reporting an AUC."
                ))],
            )

        # Gate D (Plan-2026-04-29 P0 #2): refuse experiment commits with
        # an empty metrics dict. Pre-fix, session_7a23f8edcce9
        # event-00163 called ``ratchet_commit(metrics={})`` — the metrics
        # were embedded only in the prose commit message, so the tracker
        # had no machine-checkable record. Either action.metrics OR
        # last_experiment.metrics must contain the configured primary
        # metric for the commit to proceed. ``external=True`` callers
        # are exempt (they explicitly opted into out-of-band commits).
        if not action.external and not commit_metrics_source:
            primary_metric_name = (
                deps.config.primary_metric if deps and deps.config else "auc"
            )
            return RatchetCommitObservation(
                commit_hash="",
                files=self._workspace.list_files(),
                content=[TextContent(text=(
                    "❌ ratchet_commit refused: empty metrics dict.\n"
                    f"  An experiment commit must include the primary metric "
                    f"({primary_metric_name!r}). Either:\n"
                    "  1. Pass metrics={\"<primary>\": <value>, ...} on the action, OR\n"
                    "  2. Run the experiment via run_experiment first so\n"
                    "     deps.last_experiment.metrics carries the artifact values.\n"
                    "  Commit messages with metrics in prose alone are not\n"
                    "  machine-checkable and were how stale numbers slipped\n"
                    "  through in session_7a23f8edcce9."
                    ))],
                )

        # Gate: full metric-bearing training commits must strictly improve
        # over the already committed best. get_metrics tells the agent which
        # branch to take, but ratchet_commit is the final tool boundary and
        # must fail closed if the agent calls it for a flat/worse run.
        if not action.external and deps is not None and deps.last_experiment:
            from ..orchestrator.metrics_utils import (
                is_external_test_run,
                is_non_metric_setup_run,
                recompute_best_metric_from_history,
                resolve_primary_metric,
            )

            primary_metric_name = (
                deps.config.primary_metric if deps.config else "auc"
            )
            exp = deps.last_experiment
            external_test_run = is_external_test_run(
                run_kind=str(exp.get("run_kind", "") or "")
            )
            non_metric_setup = is_non_metric_setup_run(
                commit_metrics_source,
                primary_metric_name,
                run_kind=str(exp.get("run_kind", "") or ""),
                exit_code=int(exp.get("exit_code", 0) or 0),
                error_type=str(exp.get("error_type", "") or ""),
            )
            if not non_metric_setup:
                current_value = resolve_primary_metric(
                    commit_metrics_source, primary_metric_name
                )
                if current_value <= 0:
                    return RatchetCommitObservation(
                        commit_hash="",
                        files=self._workspace.list_files(),
                        content=[TextContent(text=(
                            "❌ ratchet_commit refused: missing primary metric.\n"
                            f"  A full experiment commit must include a positive "
                            f"{primary_metric_name!r} value in artifact metrics.\n"
                            f"  Current artifact metrics: {commit_metrics_source!r}\n"
                            "  Re-run through run_experiment until the metric parser "
                            "captures the primary metric, or ratchet_revert if the "
                            "run is not usable."
                        ))],
                    )

                tracker_best = (
                    float(getattr(deps.tracker, "best_value", 0.0) or 0.0)
                    if deps.tracker
                    else 0.0
                )
                history_best = (
                    recompute_best_metric_from_history(
                        getattr(deps.tracker, "history", []),
                        primary_metric_name,
                    )
                    if deps.tracker
                    else 0.0
                )
                committed_best = max(tracker_best, history_best)
                if (
                    not external_test_run
                    and committed_best > 0
                    and current_value <= committed_best
                ):
                    return RatchetCommitObservation(
                        commit_hash="",
                        files=self._workspace.list_files(),
                        content=[TextContent(text=(
                            "❌ ratchet_commit refused: metric did not improve "
                            "committed best.\n"
                            f"  primary metric: {primary_metric_name}\n"
                            f"  current artifact {primary_metric_name}: "
                            f"{current_value:.4f}\n"
                            f"  committed best {primary_metric_name}: "
                            f"{committed_best:.4f}\n"
                            "  Use ratchet_revert to discard this non-improving "
                            "change, then try a new method."
                        ))],
                    )

        # Gate E: data protocol lock. Once a full run has been committed,
        # later commits in the same ratchet ladder must keep the data protocol
        # fixed. Otherwise the agent can "improve" by changing n_train/n_val,
        # split source, or dataset identity rather than improving the method.
        external_test_for_protocol = False
        if deps is not None and deps.last_experiment:
            try:
                from ..orchestrator.metrics_utils import is_external_test_run

                external_test_for_protocol = is_external_test_run(
                    run_kind=str(deps.last_experiment.get("run_kind", "") or "")
                )
            except Exception:
                external_test_for_protocol = False
        if not action.external and deps is not None and not external_test_for_protocol:
            locked_protocol, locked_run_id, locked_iteration = (
                _locked_data_protocol_from_tracker(deps.tracker)
            )
            if locked_protocol:
                current_protocol = _extract_data_protocol(commit_metrics_source)
                if current_protocol != locked_protocol:
                    return RatchetCommitObservation(
                        commit_hash="",
                        files=self._workspace.list_files(),
                        content=[TextContent(text=_data_protocol_change_message(
                            locked=locked_protocol,
                            current=current_protocol,
                            run_id=locked_run_id,
                            iteration=locked_iteration,
                        ))],
                    )

        # Detect > 0.5pp disagreement on the primary metric so the agent
        # sees the discrepancy in the observation text. Uses the same
        # primary_metric resolver the tracker uses, so comparisons are
        # apples-to-apples with what _finalize_iteration will record.
        disagreement_warning = ""
        if artifact_metrics and action.metrics:
            try:
                from ..orchestrator.metrics_utils import resolve_primary_metric
                primary_metric = (
                    deps.config.primary_metric if deps and deps.config else "auc"
                )
                action_value = resolve_primary_metric(action.metrics, primary_metric)
                artifact_value = resolve_primary_metric(artifact_metrics, primary_metric)
                if (
                    action_value > 0
                    and artifact_value > 0
                    and abs(action_value - artifact_value) > 0.005
                ):
                    disagreement_warning = (
                        f"\n⚠ action.metrics.{primary_metric} ({action_value:.4f}) "
                        f"differs from artifact.metrics.{primary_metric} "
                        f"({artifact_value:.4f}).\n"
                        f"   Using artifact value for tracker. If action.metrics "
                        f"represented a\n   different run, re-run run_experiment first."
                    )
            except Exception:
                pass

        try:
            commit_hash = self._workspace.commit(
                action.message,
                commit_metrics_source,
            )
        except CommitFailed as exc:
            trimmed_stderr = (exc.stderr or "").strip()[:200]
            return RatchetCommitObservation(
                commit_hash="",
                files=self._workspace.list_files(),
                content=[
                    TextContent(
                        text=(
                            f"❌ Commit failed at stage '{exc.stage}' "
                            f"(exit={exc.exit_code}): {trimmed_stderr}\n"
                            "  The last run is still pending and can be "
                            "retried after fixing the git/artifact issue. "
                            "Do not delete output/ or .evidence/ to recover."
                        )
                    )
                ],
            )

        files = self._workspace.list_files()

        _finalize_iteration(
            self._session_id,
            commit_metrics_source,
            committed=True,
            action_external=action.external,
        )

        message_text = f"Committed: {commit_hash[:8]} — {action.message}"
        if disagreement_warning:
            message_text += disagreement_warning

        return RatchetCommitObservation(
            commit_hash=commit_hash,
            files=files,
            content=[TextContent(text=message_text)],
        )


class RatchetCommitTool(ToolDefinition[RatchetCommitAction, RatchetCommitObservation]):
    name = "ratchet_commit"

    @classmethod
    def create(cls, conv_state=None, session_id: str = "", workspace=None, **params) -> Sequence[Self]:
        if session_id and workspace is None:
            from ..runtime.session_registry import get_session
            workspace = get_session(session_id).workspace
        return [
            cls(
                description=(
                    "Commit current workspace changes as an improvement. "
                    "Use this when experiment metrics improved over the previous best. "
                    "Include the new metrics in the commit."
                ),
                action_type=RatchetCommitAction,
                observation_type=RatchetCommitObservation,
                executor=RatchetCommitExecutor(workspace, session_id=session_id),
                annotations=ToolAnnotations(
                    title="Ratchet Commit",
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]


# --- Revert ---

class RatchetRevertAction(Action):
    reason: str = Field(default="", description="Why the changes are being reverted.")
    metrics: dict = Field(default_factory=dict, description="Metrics from the failed run (preserved for evidence).")
    external: bool = Field(
        default=False,
        description="See RatchetCommitAction.external.",
    )


class RatchetRevertObservation(Observation):
    reverted_to: str = Field(default="", description="Commit hash reverted to.")


class RatchetRevertExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace, session_id: str = ""):
        self._workspace = workspace
        self._session_id = session_id

    def __call__(
        self,
        action: RatchetRevertAction,
        conversation: "LocalConversation | None" = None,
    ) -> RatchetRevertObservation:
        from ..runtime.workspace import CommitFailed

        # Resolve deps once so all gates read from the same snapshot.
        deps = None
        if self._session_id:
            try:
                from ..runtime.session_registry import get_session
                deps = get_session(self._session_id)
            except KeyError:
                deps = None  # session registry lost — fall through

        # Gate: refuse reverts that were not preceded by run_experiment,
        # unless the caller explicitly opted into external mode.
        #
        # Motivating shape: agent runs ``python train.py`` via ``terminal``,
        # sees it crash, and calls ``ratchet_revert`` directly — the evidence
        # collector has no stderr/error_type/error_hint to capture for the
        # failed run. Mirrors the commit gate (session_b14b074d2268, 2026-04-20).
        #
        # The gate fires BEFORE the pre-revert code/diff/untracked capture
        # below, because that capture makes no sense if we're going to refuse
        # the call outright.
        #
        # Note: revert does NOT have a quick_check / failed-run gate. Reverting
        # a quick_check or a failed run is the correct action — we're
        # discarding the change. Only commits need those gates.
        if not action.external and deps is not None:
            if deps.last_experiment is None:
                return RatchetRevertObservation(
                    reverted_to="",
                    content=[TextContent(text=(
                        "❌ ratchet_revert requires a preceding run_experiment.\n"
                        "  Running the failed experiment through run_experiment lets "
                        "evidence capture stderr, error_type, and error_hint for the "
                        "revert record. Then retry ratchet_revert."
                    ))],
                )

            # Stale last_experiment gate (Fix A, 2026-04-21 post-fix review):
            # symmetric to the commit gate above. Without this check, a
            # revert would snapshot the older run's code/diff/stderr
            # against the newer tracker run_id, splitting lineage the same
            # way a stale commit does.
            exp_run_id = deps.last_experiment.get("run_id", "")
            current_run_id = (
                deps.iteration_state.last_run_id if deps.iteration_state else ""
            )
            if exp_run_id and current_run_id and exp_run_id != current_run_id:
                return RatchetRevertObservation(
                    reverted_to="",
                    content=[TextContent(text=(
                        f"❌ ratchet_revert refused: last_experiment is stale.\n"
                        f"  last_experiment.run_id = {exp_run_id!r}\n"
                        f"  iteration_state.last_run_id = {current_run_id!r}\n"
                        f"  The evidence collector would snapshot the older run against\n"
                        f"  the newer tracker run_id, splitting lineage. Run the current\n"
                        f"  experiment through run_experiment before reverting."
                    ))],
                )

        # Prefer artifact metrics for finalization, mirroring the commit-side
        # Gate C (2026-04-22 session 8e48c15d38cb review, Findings 1 & 6).
        # Revert usually carries action.metrics={} (failed runs have nothing
        # useful to report), but if action.metrics is populated AND the
        # artifact has metrics too, the artifact value wins — same contract
        # as commit so tracker state is consistent across both paths.
        artifact_metrics: dict = {}
        if (
            deps is not None
            and deps.last_experiment
            and isinstance(deps.last_experiment.get("metrics"), dict)
        ):
            artifact_metrics = dict(deps.last_experiment["metrics"])
        revert_metrics_source = artifact_metrics or dict(action.metrics or {})

        # Capture failed code state BEFORE reverting workspace
        # so evidence records the attempted code, not the restored baseline
        if deps is not None and deps.last_experiment is not None and self._workspace is not None:
            try:
                train_path = self._workspace.root / "train.py"
                if train_path.exists():
                    deps.last_experiment["_pre_revert_code"] = train_path.read_text(encoding="utf-8")
                import subprocess
                diff_result = subprocess.run(
                    ["git", "diff", "HEAD", "--"],
                    cwd=self._workspace.root, capture_output=True, text=True, timeout=5,
                )
                if diff_result.returncode == 0:
                    deps.last_experiment["_pre_revert_diff"] = diff_result.stdout

                # Capture untracked files (git diff HEAD -- excludes these)
                untracked_result = subprocess.run(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    cwd=self._workspace.root, capture_output=True, text=True, timeout=5,
                )
                if untracked_result.returncode == 0 and untracked_result.stdout.strip():
                    untracked = {}
                    for fname in untracked_result.stdout.strip().split("\n"):
                        fpath = self._workspace.root / fname
                        if fpath.is_file() and fpath.stat().st_size < 50_000:
                            try:
                                untracked[fname] = fpath.read_text(encoding="utf-8")
                            except Exception:
                                pass
                    if untracked:
                        deps.last_experiment["_pre_revert_untracked"] = untracked
            except Exception:
                pass

        try:
            self._workspace.revert()
        except CommitFailed as exc:
            _finalize_iteration(
                self._session_id,
                metrics=revert_metrics_source,
                committed=False,
                action_external=action.external,
            )
            trimmed_stderr = (exc.stderr or "").strip()[:200]
            return RatchetRevertObservation(
                reverted_to="",
                content=[
                    TextContent(
                        text=(
                            f"❌ Revert failed at stage '{exc.stage}' "
                            f"(exit={exc.exit_code}): {trimmed_stderr}"
                        )
                    )
                ],
            )

        current = self._workspace.get_current_commit()

        _finalize_iteration(
            self._session_id,
            metrics=revert_metrics_source,
            committed=False,
            action_external=action.external,
        )

        return RatchetRevertObservation(
            reverted_to=current,
            content=[TextContent(text=f"Reverted to {current[:8]}. Reason: {action.reason}")],
        )


class RatchetRevertTool(ToolDefinition[RatchetRevertAction, RatchetRevertObservation]):
    name = "ratchet_revert"

    @classmethod
    def create(cls, conv_state=None, session_id: str = "", workspace=None, **params) -> Sequence[Self]:
        if session_id and workspace is None:
            from ..runtime.session_registry import get_session
            workspace = get_session(session_id).workspace
        return [
            cls(
                description=(
                    "Discard all uncommitted workspace changes, reverting to "
                    "the last committed state. Use this when an experiment failed "
                    "or metrics did not improve."
                ),
                action_type=RatchetRevertAction,
                observation_type=RatchetRevertObservation,
                executor=RatchetRevertExecutor(workspace, session_id=session_id),
                annotations=ToolAnnotations(
                    title="Ratchet Revert",
                    destructiveHint=True,
                    openWorldHint=False,
                ),
            )
        ]
