"""Checkpoint tool — create and restore named workspace snapshots."""
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


class CheckpointAction(Action):
    command: str = Field(
        description=(
            "Command to execute. One of:\n"
            "  'create <name>' — save current state as a named checkpoint\n"
            "  'restore <name>' — restore workspace to a checkpoint\n"
            "  'list' — list all checkpoints\n"
            "  'delete <name>' — delete a checkpoint"
        ),
    )


class CheckpointObservation(Observation):
    checkpoint_name: str | None = Field(default=None, description="Checkpoint acted on.")
    commit_hash: str = Field(default="", description="Commit hash of checkpoint.")


class CheckpointExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace):
        self._workspace = workspace

    def __call__(
        self,
        action: CheckpointAction,
        conversation: "LocalConversation | None" = None,
    ) -> CheckpointObservation:
        parts = action.command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "create" and arg:
            return self._create(arg)
        elif cmd == "restore" and arg:
            return self._restore(arg)
        elif cmd == "list":
            return self._list()
        elif cmd == "delete" and arg:
            return self._delete(arg)
        else:
            return CheckpointObservation.from_text(
                text=(
                    "Invalid command. Use:\n"
                    "  'create <name>' — save checkpoint\n"
                    "  'restore <name>' — restore to checkpoint\n"
                    "  'list' — list checkpoints\n"
                    "  'delete <name>' — delete checkpoint"
                ),
                is_error=True,
            )

    def _create(self, name: str) -> CheckpointObservation:
        commit_hash = self._workspace.create_checkpoint(name)
        return CheckpointObservation(
            checkpoint_name=name,
            commit_hash=commit_hash,
            content=[TextContent(text=f"Checkpoint '{name}' created at {commit_hash[:8]}")],
        )

    def _restore(self, name: str) -> CheckpointObservation:
        try:
            commit_hash = self._workspace.restore_checkpoint(name)
            return CheckpointObservation(
                checkpoint_name=name,
                commit_hash=commit_hash,
                content=[TextContent(text=f"Restored to checkpoint '{name}' ({commit_hash[:8]})")],
            )
        except ValueError as e:
            return CheckpointObservation.from_text(text=str(e), is_error=True)

    def _list(self) -> CheckpointObservation:
        checkpoints = self._workspace.list_checkpoints()
        if not checkpoints:
            return CheckpointObservation(
                content=[TextContent(text="No checkpoints.")],
            )
        text = f"Checkpoints ({len(checkpoints)}):\n"
        for cp in checkpoints:
            text += f"  {cp['name']} ({cp['hash']})\n"
        return CheckpointObservation(content=[TextContent(text=text)])

    def _delete(self, name: str) -> CheckpointObservation:
        deleted = self._workspace.delete_checkpoint(name)
        if deleted:
            return CheckpointObservation(
                checkpoint_name=name,
                content=[TextContent(text=f"Checkpoint '{name}' deleted.")],
            )
        return CheckpointObservation.from_text(
            text=f"Checkpoint '{name}' not found.", is_error=True,
        )


class CheckpointTool(ToolDefinition[CheckpointAction, CheckpointObservation]):
    name = "checkpoint"

    @classmethod
    def create(cls, conv_state=None, session_id: str = "", workspace=None, **params) -> Sequence[Self]:
        if session_id and workspace is None:
            from ..runtime.session_registry import get_session
            workspace = get_session(session_id).workspace
        return [
            cls(
                description=(
                    "Manage named workspace checkpoints. Use before risky changes "
                    "so you can restore to a known-good state.\n\n"
                    "Commands:\n"
                    "  'create <name>' — save current workspace as checkpoint\n"
                    "  'restore <name>' — restore workspace to a checkpoint\n"
                    "  'list' — show all checkpoints\n"
                    "  'delete <name>' — remove a checkpoint"
                ),
                action_type=CheckpointAction,
                observation_type=CheckpointObservation,
                executor=CheckpointExecutor(workspace),
                annotations=ToolAnnotations(
                    title="Checkpoint",
                    destructiveHint=True,  # restore is destructive
                    openWorldHint=False,
                ),
            )
        ]
