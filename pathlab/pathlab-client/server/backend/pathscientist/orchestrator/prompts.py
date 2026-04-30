"""Build execution briefs for the code agent from orchestrator state."""
from __future__ import annotations

import logging
import re

from .types import ResearchSessionState

logger = logging.getLogger(__name__)


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


def _render_prepared_contract(state: ResearchSessionState) -> list[str]:
    """Return per-field lines for the prepared contract, in a stable order.

    Reads the manifest at ``state.dataset_manifest_path``. Returns ``[]`` if
    the manifest is missing or unreadable — the higher-level "Selected
    dataset" line already states the dataset name even when the contract
    is opaque, so brief rendering must not crash on a bad manifest.
    """
    path = (state.dataset_manifest_path or "").strip()
    if not path:
        return []
    try:
        from pathlib import Path

        from ..dataset.manifests import load_manifest

        manifest = load_manifest(Path(path))
    except FileNotFoundError:
        return []
    except Exception as e:
        # Don't kill brief rendering for an unreadable manifest.
        logger.warning("Failed to load manifest at %s: %s", path, e)
        return []

    contract = manifest.prepared_contract or {}
    lines: list[str] = []
    # Stable ordering: most-likely-needed first.
    for key in (
        "task_type",
        "images_dir",
        "splits_file",
        "wsi_dir",
        "labels_file",
        "n_train",
        "n_val",
        "n_slides",
        "requires_feature_extraction",
    ):
        if key in contract and contract[key] != "":
            lines.append(f"{key}: {contract[key]}")
    # Render data_mounts last (they're a dict, render compactly).
    if manifest.data_mounts:
        mounts_str = ", ".join(
            f"{h} -> {c}" for h, c in manifest.data_mounts.items()
        )
        lines.append(f"data_mounts: {mounts_str}")
    return lines


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

    # Plan T7: surface known dataset-path corrections (e.g.
    # /project/compath -> /project/vcompath) so a typo in the user
    # question doesn't burn iterations on a non-existent path. We only
    # surface a correction when the alternative actually exists on disk.
    try:
        from ..runtime.path_aliases import find_path_corrections
        corrections = find_path_corrections(state.objective.question)
    except Exception:
        corrections = []
    if corrections:
        lines.append("Resolved path hints:")
        for original, corrected in corrections:
            lines.append(f"  - {original} -> {corrected}")

    profile = (state.grounding or {}).get("task_profile") or state.task_profile or {}
    if profile:
        lines.append(
            f"Task profile: {profile.get('task_type', '?')} / {profile.get('asset_level', '?')}"
        )

    sota_status = (state.grounding or {}).get("sota_lookup_status", "")
    if sota_status:
        lines.append(f"SOTA lookup: {sota_status}")

    rag_status = (state.grounding or {}).get("rag_status", "")
    if rag_status:
        lines.append(f"RAG retrieval: {rag_status}")
        rag_errors = []
        if (state.grounding or {}).get("rag_dense_error"):
            rag_errors.append(f"dense={state.grounding['rag_dense_error']}")
        if (state.grounding or {}).get("rag_sparse_error"):
            rag_errors.append(f"sparse={state.grounding['rag_sparse_error']}")
        if (state.grounding or {}).get("rag_error"):
            rag_errors.append(str(state.grounding["rag_error"]))
        if rag_errors:
            lines.append(f"  RAG note: {'; '.join(rag_errors)}")

    online_status = (state.grounding or {}).get("online_literature_status", "")
    if online_status:
        provider = (state.grounding or {}).get("online_literature_provider", "")
        count = (state.grounding or {}).get("online_literature_count", 0)
        local_count = (state.grounding or {}).get("local_paper_count", 0)
        detail = f"provider={provider}" if provider else "provider=none"
        detail += f", online_count={count}, local_count={local_count}"
        lines.append(f"Online literature: {online_status} ({detail})")
        if (state.grounding or {}).get("online_literature_error"):
            lines.append(f"  Online literature error: {state.grounding['online_literature_error']}")

    # Dataset acquisition surface (plan 2026-04-25 T7). When acquisition has
    # actually prepared a dataset, the agent needs to see the manifest path
    # and the selected dataset's identity. When acquisition was skipped due
    # to policy or failed outright, surface the reason so the agent doesn't
    # silently assume "the data must already be there".
    if state.acquisition_status == "prepared" and state.selected_dataset:
        sel = state.selected_dataset
        lines.append("")
        lines.append(
            f"Selected dataset: {sel.get('name', '?')} "
            f"(provider: {sel.get('provider', '?')}, "
            f"access: {sel.get('access', '?')})"
        )
        if state.dataset_manifest_path:
            lines.append(f"Dataset manifest: {state.dataset_manifest_path}")

        # Surface prepared contract paths so the agent uses them directly
        # rather than re-deriving from the manifest. Read from the manifest
        # at brief-render time — cheap and avoids stuffing the contract
        # into ``state.grounding`` just to read it back here.
        contract_lines = _render_prepared_contract(state)
        if contract_lines:
            lines.append("Prepared contract:")
            lines.extend(f"  - {line}" for line in contract_lines)
    # Plan-2026-04-30 dataset-discovery T9 + provider-repair Task 0/blocker #3:
    # surface discovery + plan paths whenever they exist. For failed /
    # skipped_policy outcomes, paths come BEFORE the failure-reason line so
    # the agent reads "where to look" before "why it failed".
    grounding = state.grounding or {}
    discovery_path = grounding.get("dataset_discovery_path")
    plan_path = grounding.get("dataset_acquisition_plan_path")
    if discovery_path or plan_path:
        # Only emit a blank line if the prepared/Selected dataset block above
        # didn't already start one.
        if not (state.acquisition_status == "prepared" and state.selected_dataset):
            lines.append("")
        if discovery_path:
            lines.append(f"Dataset discovery: {discovery_path}")
        if plan_path:
            lines.append(f"Dataset acquisition plan: {plan_path}")

    if state.acquisition_status in {"skipped_policy", "failed"} and state.acquisition_notes:
        # No leading blank — discovery/plan lines already separated us.
        if not (discovery_path or plan_path):
            lines.append("")
        # Plan-2026-04-30 dataset-provider-repair Task 8: when a candidate
        # was actually picked, surface its identity so the agent sees
        # *which* dataset got blocked, not just a status string.
        if state.selected_dataset:
            sel = state.selected_dataset
            lines.append(
                f"Selected dataset candidate: {sel.get('name', '?')} "
                f"(provider: {sel.get('provider', '?')}, "
                f"access: {sel.get('access', '?')})"
            )
        lines.append(
            f"Dataset acquisition: {state.acquisition_status} "
            f"({state.acquisition_notes})"
        )

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
