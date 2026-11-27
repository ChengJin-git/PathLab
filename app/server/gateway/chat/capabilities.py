"""Read-only recovery when speculative context prefetch missed a workflow."""

from backend.services.workspaces import WorkspaceScope
from gateway.prompts.workflows import WORKFLOWS
from gateway.prompts.scoped import CHOICE_CONSTRAINTS
from .context import build_context


async def load_capability_context(user, scope: WorkspaceScope, config: dict) -> str:
    skill = config.get("skill")
    query = config.get("query")
    if (
        not isinstance(skill, str)
        or skill not in scope.enabled_skills
        or skill not in WORKFLOWS
    ):
        return "Requested capability is unavailable in this workspace. Explain briefly; do not execute it."
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return "Supply a concise query (1-500 characters) with the selected resource name or ID."
    keys = [skill]
    if (
        skill in {"training", "inference", "annotation"}
        and "data" in scope.enabled_skills
    ):
        keys.insert(0, "data")
    # An explicit model-requested annotation lookup is not limited by speculative
    # keyword prefetch: it can recover overlay evidence in any user language.
    context = await build_context(
        user,
        scope,
        tuple(keys),
        query,
        view="results" if skill == "annotation" else "default",
    )
    return CHOICE_CONSTRAINTS + "\n\n".join(WORKFLOWS[key] for key in keys) + context
