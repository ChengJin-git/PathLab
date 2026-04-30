"""SkillBrowser tool — agent discovers and loads skills autonomously."""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Self

from pydantic import Field

from openhands.sdk.llm import TextContent
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ..runtime.workspace import Workspace


class SkillBrowserAction(Action):
    command: str = Field(
        description=(
            "Command to execute. One of:\n"
            "  'list' — list all available skills with descriptions\n"
            "  'view <name>' — view details of a skill (constraints, metrics, template info)\n"
            "  'load <name>' — load skill template into workspace as train.py and set baseline"
        ),
    )


class SkillBrowserObservation(Observation):
    skill_name: str | None = Field(default=None, description="Name of the skill acted on.")
    loaded: bool = Field(default=False, description="Whether a skill template was loaded.")


class SkillBrowserExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace):
        self._workspace = workspace
        self._loaded_skill = None

    def __call__(
        self,
        action: SkillBrowserAction,
        conversation: "LocalConversation | None" = None,
    ) -> SkillBrowserObservation:
        from ..domain.skills import registry

        parts = action.command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "list":
            return self._list_skills(registry)
        elif cmd == "view" and arg:
            return self._view_skill(registry, arg)
        elif cmd == "load" and arg:
            return self._load_skill(registry, arg)
        else:
            return SkillBrowserObservation.from_text(
                text=(
                    "Invalid command. Use:\n"
                    "  'list' — list all skills\n"
                    "  'view <name>' — view skill details\n"
                    "  'load <name>' — load skill template into workspace"
                ),
                is_error=True,
            )

    def _list_skills(self, registry) -> SkillBrowserObservation:
        skills = registry.list_skills()
        text = f"Available skills ({len(skills)}):\n\n"
        for skill in skills:
            text += (
                f"  **{skill.name}**\n"
                f"    {skill.description.strip()}\n"
                f"    Task types: {skill.task_types}\n"
                f"    Primary metric: {skill.primary_metric}\n"
                f"    Template: {skill.template}\n\n"
            )
        text += "Use 'view <name>' for details or 'load <name>' to load a template."
        return SkillBrowserObservation(
            content=[TextContent(text=text)],
        )

    def _view_skill(self, registry, name: str) -> SkillBrowserObservation:
        try:
            skill = registry.get(name)
        except KeyError as e:
            return SkillBrowserObservation.from_text(
                text=f"Skill not found: {name}. Use 'list' to see available skills.",
                is_error=True,
            )

        text = f"Skill: {skill.name}\n"
        text += f"Description: {skill.description.strip()}\n\n"
        text += f"Template: {skill.template}\n"
        text += f"Task types: {skill.task_types}\n"
        text += f"Primary metric: {skill.primary_metric}\n"
        text += f"Secondary metrics: {skill.secondary_metrics}\n"
        text += f"Modifiable zones: {skill.modifiable_zones}\n\n"

        if skill.constraints:
            text += "Constraints:\n"
            for c in skill.constraints:
                text += f"  - {c}\n"
            text += "\n"

        if skill.inputs:
            text += f"Expected inputs: {json.dumps(skill.inputs, indent=2)}\n"
        if skill.outputs:
            text += f"Expected outputs: {json.dumps(skill.outputs, indent=2)}\n"

        if skill.dataset:
            fmt = skill.dataset.get("format", "unknown")
            text += f"Data format: {fmt}\n"
            dim = skill.get_feature_dim()
            text += f"Default feature dim: {dim}\n"

        text += f"\nUse 'load {name}' to load this template into the workspace."
        return SkillBrowserObservation(
            skill_name=name,
            content=[TextContent(text=text)],
        )

    def _load_skill(self, registry, name: str) -> SkillBrowserObservation:
        try:
            skill = registry.get(name)
        except KeyError:
            return SkillBrowserObservation.from_text(
                text=f"Skill not found: {name}. Use 'list' to see available skills.",
                is_error=True,
            )

        # Plan T5: defense-in-depth — surface a structured error if the
        # skill's template file is missing instead of crashing the tool
        # loop. Pre-fix, a missing patch_classification_template.py raised
        # FileNotFoundError that propagated up to the OpenHands tool
        # dispatcher and stalled the session (session_a70dd3a564c1).
        try:
            template = skill.get_template_content()
        except FileNotFoundError as e:
            return SkillBrowserObservation.from_text(
                text=(
                    f"Skill template missing for {name!r}: {e}. "
                    f"This is an installation/packaging bug — pick a "
                    f"different skill via 'list' or write code from scratch."
                ),
                is_error=True,
            )
        except Exception as e:
            return SkillBrowserObservation.from_text(
                text=(
                    f"Failed to load skill template for {name!r}: "
                    f"{type(e).__name__}: {e}"
                ),
                is_error=True,
            )
        self._workspace.set_baseline({"train.py": template})
        self._loaded_skill = skill

        constraints = skill.get_constraints_prompt()
        text = (
            f"Loaded skill '{name}' into workspace.\n"
            f"Template: train.py ({len(template)} chars, {template.count(chr(10))} lines)\n"
            f"Primary metric: {skill.primary_metric}\n"
        )
        if constraints:
            text += f"\n{constraints}"
        text += (
            "\nThe template is now the baseline in your workspace. "
            "Use file_editor to view and modify it."
        )
        return SkillBrowserObservation(
            skill_name=name,
            loaded=True,
            content=[TextContent(text=text)],
        )

    @property
    def loaded_skill(self):
        return self._loaded_skill


class SkillBrowserTool(ToolDefinition[SkillBrowserAction, SkillBrowserObservation]):
    name = "skill_browser"

    @classmethod
    def create(cls, conv_state=None, session_id: str = "", workspace=None, **params) -> Sequence[Self]:
        if session_id and workspace is None:
            from ..runtime.session_registry import get_session
            workspace = get_session(session_id).workspace
        return [
            cls(
                description=(
                    "Browse and load PathLab training skills. Skills provide "
                    "pre-built templates (code + constraints + evaluation) for "
                    "specific tasks like MIL classification, survival analysis, etc.\n\n"
                    "Commands:\n"
                    "  'list' — see all available skills\n"
                    "  'view <name>' — see skill details and constraints\n"
                    "  'load <name>' — load template into workspace as train.py"
                ),
                action_type=SkillBrowserAction,
                observation_type=SkillBrowserObservation,
                executor=SkillBrowserExecutor(workspace),
                annotations=ToolAnnotations(
                    title="Skill Browser",
                    readOnlyHint=False,  # 'load' modifies workspace
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]
