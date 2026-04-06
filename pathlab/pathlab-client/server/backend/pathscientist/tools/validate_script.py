"""ValidateScript tool — code safety + syntax validation + iteration policy."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Self

from pydantic import Field

from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation


class ValidateScriptAction(Action):
    script_content: str = Field(
        description="Python script content to validate.",
    )
    require_metrics_output: bool = Field(
        default=True,
        description="Whether to require metrics.json output.",
    )


class ValidateScriptObservation(Observation):
    valid: bool = Field(description="Whether the script passed all checks.")
    risk_level: str = Field(default="LOW", description="Safety risk level: LOW/MEDIUM/HIGH.")
    errors: list[str] = Field(default_factory=list, description="List of validation errors.")


class ValidateScriptExecutor(ToolExecutor):
    def __init__(self, session_id: str = ""):
        self._session_id = session_id

    def __call__(
        self,
        action: ValidateScriptAction,
        conversation: "LocalConversation | None" = None,
    ) -> ValidateScriptObservation:
        errors: list[str] = []
        script = action.script_content

        # 1. Syntax check
        try:
            compile(script, "<validate>", "exec")
        except SyntaxError as e:
            errors.append(f"Syntax error at line {e.lineno}: {e.msg}")

        # 2. Entry point check
        has_entry = (
            "def train()" in script
            or "def extract()" in script
            or 'if __name__ == "__main__"' in script
            or "def main()" in script
        )
        if not has_entry:
            errors.append(
                "Missing entry point: need train(), extract(), main(), "
                "or if __name__ == '__main__' block."
            )

        # 3. Metrics output check
        if action.require_metrics_output:
            if "metrics.json" not in script:
                errors.append("Script must save results to metrics.json.")

        # 4. Safety check
        from ..runtime.script_safety import ScriptRisk, assess_script_risk
        risk_level, risk_reasons = assess_script_risk(script)
        if risk_level == ScriptRisk.HIGH:
            for reason in risk_reasons:
                errors.append(f"Safety: {reason}")

        valid = len(errors) == 0

        # 5. Update iteration policy — mark this content hash as validated
        if valid and self._session_id:
            try:
                from ..runtime.session_registry import get_session
                deps = get_session(self._session_id)
                if deps.iteration_state:
                    file_hash = hashlib.md5(script.encode()).hexdigest()[:12]
                    deps.iteration_state.mark_validated(file_hash)
            except (KeyError, AttributeError):
                pass

        from openhands.sdk.llm import TextContent
        text = f"Valid: {valid}\nRisk: {risk_level.name}\n"
        if errors:
            text += "Errors:\n" + "\n".join(f"  - {e}" for e in errors)
        else:
            text += "All checks passed."

        return ValidateScriptObservation(
            valid=valid,
            risk_level=risk_level.name,
            errors=errors,
            content=[TextContent(text=text)],
            is_error=not valid,
        )


class ValidateScriptTool(ToolDefinition[ValidateScriptAction, ValidateScriptObservation]):
    name = "validate_script"

    @classmethod
    def create(cls, conv_state=None, session_id: str = "", **params) -> Sequence[Self]:
        return [
            cls(
                description=(
                    "Validate a Python training script before execution. "
                    "Checks syntax, entry points, metrics output, and safety risks. "
                    "Always validate before running an experiment."
                ),
                action_type=ValidateScriptAction,
                observation_type=ValidateScriptObservation,
                executor=ValidateScriptExecutor(session_id=session_id),
                annotations=ToolAnnotations(
                    title="Validate Script",
                    readOnlyHint=True,
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]
