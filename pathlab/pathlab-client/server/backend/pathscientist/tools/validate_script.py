"""ValidateScript tool — code safety + syntax validation + iteration policy.

Review Finding 1 (2026-04-22) fix: ``validate_script`` previously hashed the
``script_content`` string supplied by the LLM and handed that hash to
``iteration_state.last_validated_hash``. ``run_experiment`` then computed a
fresh hash of the on-disk ``train.py`` and compared against that value.
Because the agent's ``script_content`` parameter was free to drift from disk
(stale in-context copy, whitespace differences, re-generated from memory),
the two hashes diverged even when nobody had edited the file between
validate and run — producing the observed "Valid: True"/"Policy violation"
pairs in event-00163/00165 and event-00290/00292 of session_3f1795098784.

The fix: validate (and hash) the on-disk file that ``run_experiment`` will
actually execute. ``script_content`` is still accepted so the agent can
show its intent, but if it disagrees with disk we refuse validation and
tell the agent which side is stale. The refusal text from
``run_experiment`` is made actionable by ``tools.run_experiment`` so the
agent can see exactly why the handoff failed.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Self

from pydantic import Field

from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation


# Plan-2026-04-28 P1 #6: scan scripts for ``get_extractor("X")`` /
# ``get_extractor('X')`` so we can preflight the runtime import of X
# before quick-check spends an iteration on a missing module.
_EXTRACTOR_NAME_RE = re.compile(
    r"""get_extractor\s*\(\s*(?P<q>['"])(?P<name>[A-Za-z0-9_\-]+)(?P=q)"""
)


def _extract_extractor_names(script: str) -> list[str]:
    """Return the set of extractor names referenced via
    ``get_extractor("...")``. Deterministic order = first-seen."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _EXTRACTOR_NAME_RE.finditer(script or ""):
        n = m.group("name")
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _check_extractor_available(name: str) -> str:
    """Return a short error message when extractor ``name`` cannot be
    loaded by the runtime registry, or "" when it's importable.

    We call ``_resolve_extractor_class`` (lazy class load), NOT
    ``get_extractor`` (which would also try to load weights) — the goal
    is to catch missing-runtime-dependency cases like
    ``No module named 'conch'`` (session_a70dd3a564c1) without paying
    the weight-load cost.
    """
    try:
        # Local import: registry pulls in torch + extractor base which
        # we don't need at module load time.
        from ..domain.templates.common.extractors.registry import (
            _resolve_extractor_class,
        )
    except Exception as e:
        # Registry itself unimportable — let the script run; we have no
        # ground truth here.
        return ""
    try:
        _resolve_extractor_class(name)
    except ImportError as e:
        return f"ImportError: {e}"
    except ValueError as e:
        # Unknown extractor name — surface as well so the agent doesn't
        # call get_extractor("uno") thinking it's UNI.
        return f"unknown name: {e}"
    except Exception as e:
        # Any other failure (network, file missing) is informational.
        return f"{type(e).__name__}: {e}"
    return ""


class ValidateScriptAction(Action):
    script_content: str = Field(
        default="",
        description=(
            "Python script content to validate. Optional — if omitted, the "
            "on-disk file at ``script_path`` is read and validated. "
            "If provided, it must match the on-disk file byte-for-byte; "
            "otherwise validation refuses with a disk/content mismatch error."
        ),
    )
    script_path: str = Field(
        default="train.py",
        description=(
            "Path (relative to the workspace root) of the script to validate. "
            "This is the SAME path that ``run_experiment`` will execute; "
            "the hash recorded by validate_script is computed from the file "
            "at this path so the handoff to ``run_experiment`` cannot drift."
        ),
    )
    require_metrics_output: bool = Field(
        default=True,
        description="Whether to require metrics.json output.",
    )


class ValidateScriptObservation(Observation):
    valid: bool = Field(description="Whether the script passed all checks.")
    risk_level: str = Field(default="LOW", description="Safety risk level: LOW/MEDIUM/HIGH.")
    errors: list[str] = Field(default_factory=list, description="List of validation errors.")
    validated_hash: str = Field(
        default="",
        description=(
            "The 12-hex MD5 prefix of the on-disk script that was validated. "
            "Empty string if validation failed or the file could not be read."
        ),
    )
    validated_path: str = Field(
        default="",
        description="Workspace-relative path of the script that was validated.",
    )


class ValidateScriptExecutor(ToolExecutor):
    def __init__(self, session_id: str = ""):
        self._session_id = session_id

    def _get_workspace(self):
        """Return the workspace for this session, or ``None`` if unavailable."""
        if not self._session_id:
            return None
        try:
            from ..runtime.session_registry import get_session
            return get_session(self._session_id).workspace
        except (KeyError, AttributeError):
            return None

    def _get_iteration_state(self):
        """Return the iteration state for this session, or ``None`` if unavailable."""
        if not self._session_id:
            return None
        try:
            from ..runtime.session_registry import get_session
            return get_session(self._session_id).iteration_state
        except (KeyError, AttributeError):
            return None

    def __call__(
        self,
        action: ValidateScriptAction,
        conversation: "LocalConversation | None" = None,
    ) -> ValidateScriptObservation:
        from openhands.sdk.llm import TextContent

        errors: list[str] = []
        script_path = action.script_path or "train.py"

        # 1. Resolve the on-disk script. The hash we record must match the
        #    file ``run_experiment`` will hash — so we read the file from
        #    ``workspace.root / script_path`` and validate that.
        workspace = self._get_workspace()
        disk_content: str | None = None
        validated_hash = ""
        if workspace is not None:
            disk_path = workspace.root / script_path
            try:
                disk_content = disk_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                errors.append(
                    f"Script not found on disk at '{script_path}'. "
                    "Write the file via file_editor first (run_experiment "
                    "executes the file on disk, not inline content)."
                )
            except OSError as exc:
                errors.append(f"Could not read script '{script_path}': {exc}")

        # 2. Source of truth: disk content when available. If the agent ALSO
        #    provided ``script_content``, verify it matches disk — a mismatch
        #    means the agent's view is stale (or edits weren't persisted).
        #    Catching this at validate-time is what stops the
        #    "Valid: True → Policy violation" handoff bug.
        supplied = action.script_content or ""
        script_for_checks: str
        if disk_content is not None:
            script_for_checks = disk_content
            if supplied and supplied != disk_content:
                supplied_hash = hashlib.md5(supplied.encode()).hexdigest()[:12]
                disk_hash = hashlib.md5(disk_content.encode()).hexdigest()[:12]
                errors.append(
                    "script_content does not match the file on disk "
                    f"('{script_path}'). "
                    f"supplied_hash = {supplied_hash}, "
                    f"disk_hash = {disk_hash}. "
                    "run_experiment will execute the on-disk file, so "
                    "either write your updated content to disk via "
                    "file_editor before validating, or omit script_content "
                    "and validate the file as-is."
                )
        elif supplied:
            # No workspace (e.g. legacy callers / unit tests): fall back to
            # the supplied content. We still record a hash so unit tests that
            # exercise the IterationState handoff remain meaningful, but the
            # mismatch shape above is preferred in production.
            script_for_checks = supplied
        else:
            errors.append(
                "No script to validate: provide script_content or ensure "
                f"'{script_path}' exists on disk."
            )
            script_for_checks = ""

        # 3. Syntax / entry-point / metrics / safety checks on the source-of-truth.
        if script_for_checks:
            try:
                compile(script_for_checks, "<validate>", "exec")
            except SyntaxError as e:
                errors.append(f"Syntax error at line {e.lineno}: {e.msg}")

            has_entry = (
                "def train()" in script_for_checks
                or "def extract()" in script_for_checks
                or 'if __name__ == "__main__"' in script_for_checks
                or "def main()" in script_for_checks
            )
            if not has_entry:
                errors.append(
                    "Missing entry point: need train(), extract(), main(), "
                    "or if __name__ == '__main__' block."
                )

            if action.require_metrics_output:
                if "metrics.json" not in script_for_checks:
                    errors.append("Script must save results to metrics.json.")

            from ..runtime.script_safety import ScriptRisk, assess_script_risk
            risk_level, risk_reasons = assess_script_risk(script_for_checks)
            if risk_level == ScriptRisk.HIGH:
                for reason in risk_reasons:
                    errors.append(f"Safety: {reason}")

            # Plan-2026-04-28 P1 #6: extractor availability preflight.
            # Pre-fix, a script that called `get_extractor("conch")`
            # passed validate_script but quick-check died with
            # `No module named 'conch'` — wasted an iteration. Now we
            # try the lazy import at validate time and surface
            # unavailable extractors as errors before the run starts.
            for ext_name in _extract_extractor_names(script_for_checks):
                err = _check_extractor_available(ext_name)
                if err:
                    errors.append(
                        f"Extractor '{ext_name}' is not available at "
                        f"runtime: {err}. Pick a different extractor "
                        f"from the installed list (see environment context "
                        f"in the execution brief)."
                    )
        else:
            from ..runtime.script_safety import ScriptRisk
            risk_level = ScriptRisk.LOW

        valid = len(errors) == 0

        # 4. On success, record the hash of the file ``run_experiment`` will
        #    hash — never the LLM-supplied string. This is the crux of the
        #    Finding 1 fix.
        if valid and script_for_checks:
            validated_hash = hashlib.md5(script_for_checks.encode()).hexdigest()[:12]
            iteration_state = self._get_iteration_state()
            if iteration_state is not None:
                iteration_state.mark_validated(validated_hash)
                # Remember the path too so run_experiment can surface it in
                # a precise refusal message when the paths diverge.
                iteration_state.last_validated_path = script_path

        text = f"Valid: {valid}\nRisk: {risk_level.name}\n"
        if validated_hash:
            text += f"Validated: {script_path} (hash {validated_hash})\n"
        if errors:
            text += "Errors:\n" + "\n".join(f"  - {e}" for e in errors)
        else:
            text += "All checks passed."

        return ValidateScriptObservation(
            valid=valid,
            risk_level=risk_level.name,
            errors=errors,
            validated_hash=validated_hash,
            validated_path=script_path if validated_hash else "",
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
                    "Checks syntax, entry points, metrics output, and safety "
                    "risks AGAINST THE FILE ON DISK at ``script_path`` "
                    "(default: train.py). The recorded hash is the disk "
                    "file's hash, so ``run_experiment`` sees the same hash "
                    "and the validate→run handoff cannot drift. Supply "
                    "script_content only for a cross-check against disk; if "
                    "it disagrees, validation refuses with both hashes shown."
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
