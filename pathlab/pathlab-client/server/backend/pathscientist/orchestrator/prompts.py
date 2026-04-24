"""Build execution briefs for the code agent from orchestrator state."""
from __future__ import annotations

import re

from .types import ResearchSessionState


def _normalize_match_text(value: str) -> str:
    """Normalize labels so dataset matching survives paths, dashes, and spaces."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _objective_mentions_dataset(state: ResearchSessionState, dataset: str) -> bool:
    """Check whether the objective explicitly points at a dataset name."""
    if not dataset:
        return False

    haystack = " ".join(
        part
        for part in (state.objective.dataset_hint, state.objective.question)
        if part
    )
    if not haystack:
        return False

    return _normalize_match_text(dataset) in _normalize_match_text(haystack)


def _select_target_baseline(state: ResearchSessionState, baselines: list[dict]) -> dict | None:
    """Pick a hard target only when the objective matches the baseline dataset."""
    matching = [
        baseline
        for baseline in baselines
        if _objective_mentions_dataset(state, str(baseline.get("dataset", "")))
    ]
    if not matching:
        return None
    return max(matching, key=lambda baseline: float(baseline.get("metric_value", 0)))


def build_execution_brief(state: ResearchSessionState) -> str:
    """Build a message to seed the code agent with execution context.

    The code agent receives this as a user message and does not know
    about the orchestrator. The brief should contain everything the
    agent needs to start working.
    """
    skill = state.grounding.get("selected_skill", "")
    route = state.grounding.get("route", "free")

    lines = [
        f"Research objective: {state.objective.question}",
        f"Primary metric: {state.objective.success_metric}",
        f"Iteration budget: {state.max_iterations}",
    ]

    if skill:
        lines.append(f"Selected skill: {skill}")
        if not state.run_history:
            # First execution turn — load the skill template to initialize workspace
            lines.append(f"Load this skill with `skill_browser load {skill}` before writing code.")
        else:
            # Later turns — skill already loaded, do NOT reload (it overwrites workspace)
            lines.append(f"Skill '{skill}' is already loaded. Do NOT call skill_browser load again.")
    else:
        lines.append("No skill pre-selected (free mode). Check available skills first, or write code from scratch.")

    if state.objective.dataset_hint:
        lines.append(f"Dataset hint: {state.objective.dataset_hint}")

    if state.objective.constraints:
        lines.append("Constraints:")
        for c in state.objective.constraints:
            lines.append(f"  - {c}")

    # Literature-grounded baselines
    baselines = state.grounding.get("baselines", [])
    if baselines:
        lines.append("")
        lines.append("Prior work:")
        for b in baselines[:3]:  # top 3
            method = b.get("method", "?")
            metric = b.get("metric_name", "?")
            value = b.get("metric_value", 0)
            dataset = b.get("dataset", "?")
            paper_id = b.get("paper_id", "")
            citation = f" [{paper_id}]" if paper_id else ""
            lines.append(f"  - {method} achieves {value:.2f} {metric} on {dataset}{citation}")
        target = _select_target_baseline(state, baselines)
        if target is not None:
            lines.append(
                "Your target: beat "
                f"{target.get('metric_value', 0):.2f} {target.get('metric_name', '')} "
                f"on {target.get('dataset', '?')}."
            )
        else:
            lines.append(
                "No same-dataset literature baseline was found; use the cited "
                "prior work as reference, not as a hard target."
            )

    # --- Literature-grounded SOTA target (plan 2026-04-23) -----------------
    target_value = state.objective.target_metric_value
    if target_value > 0.0:
        target_payload = (state.grounding or {}).get("sota_target") or {}
        source_kind = (target_payload.get("source") or "").lower()
        target_src = state.objective.target_source or "(unknown source)"
        conf = (
            target_payload.get("confidence")
            or state.objective.target_confidence
            or "medium"
        ).lower()
        hard_target = source_kind in {"pwc", "local_store"}
        label = "Your SOTA target" if hard_target else "Literature reference target"
        verb = "beat" if hard_target else "roughly match"
        lines.append("")
        lines.append(
            f"{label}: {verb} "
            f"{target_value:.2f} {state.objective.success_metric} "
            f"on {state.objective.dataset_hint or 'the benchmark'} "
            f"({target_src}) ({conf} confidence)."
        )
        if hard_target:
            if conf == "low":
                lines.append(
                    "  Note: confidence is low — treat this target as a guide, "
                    "not a hard ceiling; the literature value may be noisy."
                )
        else:
            lines.append(
                "  Note: this value comes from abstract-level literature extraction; "
                "treat it as directional guidance, not a strict stopping rule."
            )

    # Evidence snippets from RAG retrieval
    passages = state.grounding.get("passages", [])
    if passages:
        lines.append("")
        lines.append("Evidence from prior work:")
        for p in passages:
            paper_id = p.get("paper_id", "?")
            chunk_id = p.get("chunk_id", "")
            section = p.get("section", "")
            text_preview = p.get("text", "")[:200]
            cite_handle = f"[{paper_id}#{chunk_id}]" if chunk_id else f"[{paper_id}]"
            section_tag = f" ({section})" if section else ""
            lines.append(f"  - {cite_handle}{section_tag}: {text_preview}")

    # Related papers from online search (when no baselines are available)
    papers = state.grounding.get("papers", [])
    if papers and not baselines:
        lines.append("")
        lines.append("Related papers:")
        for p in papers[:5]:
            pid = p.get("paper_id", "?")
            title = p.get("title", "?")
            year = p.get("year", "")
            year_str = f" ({year})" if year else ""
            lines.append(f"  - {title}{year_str} [{pid}]")

    # Context from previous iterations (if resuming mid-session)
    if state.run_history:
        lines.append("")
        lines.append(f"Previous iterations: {len(state.run_history)}")
        lines.append(f"Current best: {state.best_metric_value:.4f} ({state.best_run_id})")
        lines.append("Continue improving from the current workspace state.")

    lines.append("")
    lines.append(
        "You are in the execution stage. Follow the mandatory workflow: "
        "get_workspace_info, think, edit, validate, quick_check, full run, "
        "get_metrics, then commit or revert."
    )

    return "\n".join(lines)
