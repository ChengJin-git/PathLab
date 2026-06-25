"""GetWorkspaceInfo tool — workspace state and git history."""
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


class GetWorkspaceInfoAction(Action):
    """No parameters needed — reads current workspace state."""
    pass


class GetWorkspaceInfoObservation(Observation):
    workspace_dir: str = Field(default="", description="Workspace root directory.")
    current_files: list[str] = Field(default_factory=list, description="Files in workspace.")
    git_history: list[dict] = Field(default_factory=list, description="Git commit history.")
    current_script: str = Field(default="", description="Content of train.py (main script).")


class GetWorkspaceInfoExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace):
        self._workspace = workspace

    def __call__(
        self,
        action: GetWorkspaceInfoAction,
        conversation: "LocalConversation | None" = None,
    ) -> GetWorkspaceInfoObservation:
        files = self._workspace.list_files()
        history = self._workspace.get_history()
        script = self._workspace.read_file("train.py") or ""

        checkpoints = self._workspace.list_checkpoints()

        text = f"Workspace: {self._workspace.root}\n"
        text += f"Files: {', '.join(files)}\n"
        text += f"Git history ({len(history)} commits):\n"
        for h in history[:10]:
            text += f"  {h.hash[:8]} {h.message}\n"
        if checkpoints:
            text += f"\nCheckpoints ({len(checkpoints)}):\n"
            for cp in checkpoints:
                text += f"  {cp['name']} ({cp['hash']})\n"
        if script:
            preview = script[:3000]
            if len(script) > 3000:
                preview += f"\n... ({len(script)} total chars)"
            text += f"\ntrain.py:\n{preview}"

        return GetWorkspaceInfoObservation(
            workspace_dir=str(self._workspace.root),
            current_files=files,
            git_history=[{"hash": h.hash, "message": h.message, "timestamp": h.timestamp} for h in history],
            current_script=script,
            content=[TextContent(text=text)],
        )


class GetWorkspaceInfoTool(ToolDefinition[GetWorkspaceInfoAction, GetWorkspaceInfoObservation]):
    name = "get_workspace_info"

    @classmethod
    def create(cls, conv_state=None, session_id: str = "", workspace=None, **params) -> Sequence[Self]:
        if session_id and workspace is None:
            from ..runtime.session_registry import get_session
            workspace = get_session(session_id).workspace
        return [
            cls(
                description=(
                    "Get current workspace state: files, git history, and "
                    "the content of the main training script. "
                    "Use this to understand what code exists before making changes."
                ),
                action_type=GetWorkspaceInfoAction,
                observation_type=GetWorkspaceInfoObservation,
                executor=GetWorkspaceInfoExecutor(workspace),
                annotations=ToolAnnotations(
                    title="Workspace Info",
                    readOnlyHint=True,
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]
