"""Ratchet tools — git commit improvements / revert failures."""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Self
from uuid import uuid4

from pydantic import Field

from openhands.sdk.llm import TextContent
from openhands.sdk.event import ObservationEvent
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ..runtime.workspace import Workspace


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


def _finalize_iteration(session_id: str, metrics: dict, committed: bool) -> None:
    """Update tracker and iteration state after a commit or revert.

    This is the single canonical finalization path — both ratchet_commit
    and ratchet_revert call it so orchestrator sees consistent state.
    """
    if not session_id:
        return
    try:
        from ..runtime.session_registry import get_session
        deps = get_session(session_id)
        resolved_metrics = _resolve_finalization_metrics(session_id, metrics)

        # Capture pre-increment iteration index — this is the canonical iteration number
        # for tracker, evidence, and orchestrator to all use consistently
        pre_increment_iteration = deps.iteration_state.iteration_index if deps.iteration_state else (deps.tracker.iteration if deps.tracker else 0)

        # Canonical run_id for this finalization — ensure_run_id() auto-generates
        # one if the agent reached this path without running run_experiment,
        # so tracker history, iteration state, and evidence all share a single
        # traceable identifier.
        if deps.iteration_state:
            run_id = deps.iteration_state.ensure_run_id()
        else:
            run_id = uuid4().hex[:8]

        # Update tracker
        if deps.tracker:
            deps.tracker.record(resolved_metrics, committed=committed, iteration=pre_increment_iteration, run_id=run_id)

        # Update iteration state (increments iteration_index).
        # Append to finalized_run_ids BEFORE record_iteration so the canonical
        # list stays consistent with the tracker entry we just wrote.
        if deps.iteration_state:
            deps.iteration_state.finalized_run_ids.append(run_id)
            deps.iteration_state.record_iteration(metrics=resolved_metrics, committed=committed)

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

        # Collect evidence if last_experiment is available
        if deps.last_experiment and deps.workspace:
            try:
                from ..evidence.collector import EvidenceCollector
                from ..evidence.store import EvidenceStore
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
                    }.items()
                })
                # Forward pre-revert snapshots if present
                if "_pre_revert_code" in exp:
                    collector._experiment["_pre_revert_code"] = exp["_pre_revert_code"]
                if "_pre_revert_diff" in exp:
                    collector._experiment["_pre_revert_diff"] = exp["_pre_revert_diff"]
                if "_pre_revert_untracked" in exp:
                    collector._experiment["_pre_revert_untracked"] = exp["_pre_revert_untracked"]
                collector.finalize(committed=committed, iteration=pre_increment_iteration)
                deps.last_experiment = None  # clear after collection
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Evidence collection failed: {e}")
    except (KeyError, AttributeError):
        pass


# --- Commit ---

class RatchetCommitAction(Action):
    message: str = Field(description="Commit message describing the improvement.")
    metrics: dict = Field(default_factory=dict, description="Metrics to record with the commit.")


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

        try:
            commit_hash = self._workspace.commit(action.message, action.metrics)
        except CommitFailed as exc:
            _finalize_iteration(
                self._session_id, action.metrics, committed=False,
            )
            trimmed_stderr = (exc.stderr or "").strip()[:200]
            return RatchetCommitObservation(
                commit_hash="",
                files=self._workspace.list_files(),
                content=[
                    TextContent(
                        text=(
                            f"\u274c Commit failed at stage '{exc.stage}' "
                            f"(exit={exc.exit_code}): {trimmed_stderr}"
                        )
                    )
                ],
            )

        files = self._workspace.list_files()

        _finalize_iteration(self._session_id, action.metrics, committed=True)

        return RatchetCommitObservation(
            commit_hash=commit_hash,
            files=files,
            content=[TextContent(text=f"Committed: {commit_hash[:8]} \u2014 {action.message}")],
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

        # Capture failed code state BEFORE reverting workspace
        # so evidence records the attempted code, not the restored baseline
        if self._session_id:
            try:
                from ..runtime.session_registry import get_session
                deps = get_session(self._session_id)
                if deps.last_experiment is not None:
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
                self._session_id, metrics=action.metrics, committed=False,
            )
            trimmed_stderr = (exc.stderr or "").strip()[:200]
            return RatchetRevertObservation(
                reverted_to="",
                content=[
                    TextContent(
                        text=(
                            f"\u274c Revert failed at stage '{exc.stage}' "
                            f"(exit={exc.exit_code}): {trimmed_stderr}"
                        )
                    )
                ],
            )

        current = self._workspace.get_current_commit()

        _finalize_iteration(self._session_id, metrics=action.metrics, committed=False)

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
