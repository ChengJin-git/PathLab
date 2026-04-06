"""Ratchet tools — git commit improvements / revert failures."""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Self

from pydantic import Field

from openhands.sdk.llm import TextContent
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ..runtime.workspace import Workspace


# --- Commit ---

class RatchetCommitAction(Action):
    message: str = Field(description="Commit message describing the improvement.")
    metrics: dict = Field(default_factory=dict, description="Metrics to record with the commit.")


class RatchetCommitObservation(Observation):
    commit_hash: str = Field(default="", description="Git commit hash.")
    files: list[str] = Field(default_factory=list, description="Files in workspace.")


class RatchetCommitExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace):
        self._workspace = workspace

    def __call__(
        self,
        action: RatchetCommitAction,
        conversation: "LocalConversation | None" = None,
    ) -> RatchetCommitObservation:
        commit_hash = self._workspace.commit(action.message, action.metrics)
        files = self._workspace.list_files()
        return RatchetCommitObservation(
            commit_hash=commit_hash,
            files=files,
            content=[TextContent(text=f"Committed: {commit_hash[:8]} — {action.message}")],
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
                executor=RatchetCommitExecutor(workspace),
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


class RatchetRevertObservation(Observation):
    reverted_to: str = Field(default="", description="Commit hash reverted to.")


class RatchetRevertExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace):
        self._workspace = workspace

    def __call__(
        self,
        action: RatchetRevertAction,
        conversation: "LocalConversation | None" = None,
    ) -> RatchetRevertObservation:
        self._workspace.revert()
        current = self._workspace.get_current_commit()
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
                executor=RatchetRevertExecutor(workspace),
                annotations=ToolAnnotations(
                    title="Ratchet Revert",
                    destructiveHint=True,
                    openWorldHint=False,
                ),
            )
        ]
