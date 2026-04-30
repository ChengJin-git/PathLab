"""Phase 1 grounding: LLM-based skill selection and task routing.

Uses the agent's LLM to choose the best matching skill from the registry
based on the user's research objective. Falls back to "free" mode if no
skill matches or if the LLM/registry is unavailable.

Plan-2026-04-29 grounding-routing-repair: the order is now
``dataset_hint → heuristic_profile → skill_selection → final_profile →
task_type → retrieval/RAG/SOTA``. ``selected_skill`` is the canonical
high-confidence task signal; ``task_type`` (coarse) is derived from it
via ``_SKILL_TO_COARSE_TASK`` so every retrieval path agrees.
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from ..config import PathScientistConfig
from ..dataset.llm_task_profile import (
    extract_task_profile_enrichment,
    merge_task_profile_enrichment,
)
from ..dataset.task_profile import infer_task_profile
from ..dataset.types import TaskProfile
from ..llm_client import build_chat_llm, extract_text, invoke_chat_llm, make_llm_config
from ..orchestrator.types import ResearchObjective
from .objective_extractor import extract_dataset_and_task

if TYPE_CHECKING:
    from ..literature.sota_lookup import SotaLookup

logger = logging.getLogger(__name__)


# Plan-2026-04-29 grounding-routing-repair Task 3: canonical mapping from
# selected_skill (the high-confidence final routing decision) to coarse
# task_type used by literature/RAG/SOTA. Single source of truth so RAG
# task_type, baseline task_type, and SOTA task_type can never silently
# disagree with the chosen skill.
_SKILL_TO_COARSE_TASK: dict[str, str] = {
    "patch_classification": "classification",
    "mil_classification": "classification",
    "patch_segmentation": "segmentation",
    "survival_analysis": "survival",
    "feature_extraction": "feature_extraction",
}


def _coarse_task_type_from_skill(skill: str) -> str:
    return _SKILL_TO_COARSE_TASK.get((skill or "").strip().lower(), "")


def _load_available_skills() -> list[dict[str, str]]:
    """Load the skill registry once. Returns [] when unavailable."""
    try:
        from ..domain.skills import registry

        registry.load_all()
        return [
            {"name": s.name, "description": s.description}
            for s in registry.list_skills()
        ]
    except Exception as e:
        logger.warning(f"Skill registry unavailable: {e}")
        return []


def _resolve_task_profile_llm_parser(llm_parser, llm_config):
    """Return a raw text LLM caller for task-profile enrichment, if available."""
    if llm_parser is not None:
        return llm_parser
    if llm_config is None:
        return None
    try:
        from ..runtime.metric_parser import build_llm_text_caller

        return build_llm_text_caller(llm_config)
    except Exception as e:
        logger.debug("Task-profile LLM caller unavailable: %s", e)
        return None


def _build_skill_selection_prompt(
    objective: ResearchObjective,
    skills: list[dict],
    *,
    profile: TaskProfile | None = None,
) -> str:
    """Build a prompt asking the LLM to select the best skill.

    Plan-2026-04-29 grounding-routing-repair Task 3 Step 5b: when a
    heuristic profile is supplied we surface its preferred_skill / organ
    / prediction_target as a hint. Pre-fix the LLM saw only the question
    and the skill list — CRC-MSI prompts hit ``selected_skill="none"``
    because there was no anchor. With the hint the LLM can confirm or
    explicitly override.
    """
    skill_list = "\n".join(
        f"- **{s['name']}**: {s['description']}"
        for s in skills
    )
    hint_block = ""
    if profile is not None:
        bits = [f"preferred_skill={profile.preferred_skill}"]
        if profile.organ:
            bits.append(f"organ={profile.organ}")
        if profile.prediction_target:
            bits.append(f"target={profile.prediction_target}")
        hint_block = (
            "\n\n## Heuristic Suggestion (you may confirm or override)\n"
            + ", ".join(bits)
        )
    return f"""You are a research task router for computational pathology.

Given the following research objective, select the most appropriate skill template.
If none of the skills match, respond with "none".

## Research Objective
{objective.question}{hint_block}

## Available Skills
{skill_list}

Respond with ONLY a JSON object, no other text:
{{"selected_skill": "<skill_name or none>", "reason": "<one sentence why>"}}"""


def _llm_select_skill(
    objective: ResearchObjective,
    skills: list[dict],
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    llm_config: PathScientistConfig | None = None,
    profile: TaskProfile | None = None,
) -> dict[str, str]:
    """Use LLM to select the best skill for the objective."""
    config = make_llm_config(
        config=llm_config,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
    )
    llm = build_chat_llm(
        config,
        component="skill selection",
        usage_id="grounding",
        temperature=0.0,
    )

    prompt = _build_skill_selection_prompt(objective, skills, profile=profile)

    try:
        from openhands.sdk.llm import Message, TextContent
    except Exception:
        # Unit tests monkeypatch the LLM builder/invoker without installing
        # OpenHands. Provide the tiny shape those tests need; real runtime
        # still uses the SDK classes when available.
        from dataclasses import dataclass

        @dataclass
        class TextContent:  # type: ignore[no-redef]
            text: str

        @dataclass
        class Message:  # type: ignore[no-redef]
            role: str
            content: list

    response = invoke_chat_llm(
        llm,
        messages=[Message(role="user", content=[TextContent(text=prompt)])],
    )

    # Parse response
    text = extract_text(response).strip()
    # Handle markdown code blocks
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Handle thinking blocks
    if "<think>" in text:
        text = text.split("</think>")[-1].strip()

    try:
        result = json.loads(text)
        return {
            "selected_skill": result.get("selected_skill", "none"),
            "reason": result.get("reason", ""),
        }
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM skill selection response: {text[:200]}")
        return {"selected_skill": "none", "reason": "parse_error"}


def _resolve_skill_fallback(
    objective: ResearchObjective,
    available_names: list[str],
    *,
    profile: TaskProfile | None = None,
) -> tuple[str, str]:
    """Plan-2026-04-29 P1-4: skill fallback chain when LLM returns
    none/unknown/parse_error.

    Order:
      1. Keyword heuristic — ``_heuristic_skill_candidate`` is more
         specific (catches survival_analysis / patch_segmentation /
         feature_extraction) than the task profile's broad default.
      2. ``task_profile.preferred_skill`` — the heuristic-derived broad
         default ("patch_classification" or "mil_classification"). Pre-
         fix the CRC-MSI prompt with no patch/mil/etc. keywords landed
         in free mode here even though the task profile clearly named
         patch_classification.

    Step 2 only fires when the profile has a *specific* signal — organ,
    prediction_target, or an explicit dataset_hint. A truly generic
    prompt ("try improving the benchmark") has no such signal and stays
    in free mode (no task profile = no fallback). This preserves
    pre-existing T4 contract test
    ``test_grounding_does_not_force_skill_for_generic_question``.

    Plan-2026-04-29 grounding-routing-repair Task 3 Step 4b: callers
    pass the heuristic profile in to avoid recomputing it. ``profile=None``
    keeps backwards compat for callers that don't have one.

    Returns ``("", "")`` when neither path produces a registered skill.
    """
    candidate = _heuristic_skill_candidate(objective)
    if candidate and candidate in available_names:
        return candidate, "heuristic"
    if profile is None:
        try:
            profile = infer_task_profile(
                objective.question,
                selected_skill="",
                dataset_hint=objective.dataset_hint or "",
            )
        except Exception as exc:
            logger.warning(
                "Skill fallback: infer_task_profile failed: %s", exc,
            )
            return "", ""
    has_signal = bool(
        profile.organ
        or profile.prediction_target
        or (objective.dataset_hint or "").strip()
    )
    if not has_signal:
        return "", ""
    preferred = (profile.preferred_skill or "").strip()
    if preferred and preferred in available_names:
        return preferred, "task_profile_preferred_skill"
    return "", ""


def _heuristic_skill_candidate(objective: ResearchObjective) -> str:
    """Plan T4: deterministic skill routing fallback for clearly-shaped tasks.

    Used only when the LLM router returns ``none``/``parse_error``/unknown
    skill — keeps obvious patch-classification or MIL questions from falling
    through to free mode (session_a70dd3a564c1: a "patch-level MSI classifier"
    objective ended up with selected_skill="" because the LLM returned
    parse_error and the existing path quietly accepted free mode).

    Plan-2026-04-29 grounding-routing-repair Task 4: regex word-boundaries
    so ``"mil"`` no longer matches inside ``"similar"`` / ``"familial"``,
    and ``"patch"`` / ``"tile"`` use word boundaries instead of space-
    padded substring tricks.

    Returns "" when the task shape is genuinely ambiguous so we don't force
    an unrelated skill on a generic prompt.
    """
    text = " ".join([
        objective.question or "",
        objective.preferred_skill or "",
        objective.dataset_hint or "",
    ]).lower()

    # Order matters: more specific signals first. WSI/MIL/slide-level beats
    # patch because "slide" implies a different task even if the user said
    # "patch" elsewhere.
    if re.search(
        r"(?<![a-z0-9])mil(?![a-z0-9])|"
        r"\bwsi\b|"
        r"\bslide[- ]level\b|"
        r"\bwhole slide\b",
        text,
    ):
        return "mil_classification"
    if any(tok in text for tok in ("survival", "c-index", "cindex", "concordance")):
        return "survival_analysis"
    if any(tok in text for tok in ("segment", "segmentation", "mask", " iou", "dice")):
        return "patch_segmentation"
    if any(tok in text for tok in ("feature extraction", "extract features", "foundation model")):
        return "feature_extraction"
    # Patch must come last — the keyword is broad ("patch", "tile") and
    # would otherwise eat WSI/MIL prompts that also mention patches.
    if re.search(r"\bpatch(?:es)?\b|\bpatch[- ]level\b|\btile(?:s)?\b", text):
        return "patch_classification"
    return ""


def ground_objective(
    objective: ResearchObjective,
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    llm_config: PathScientistConfig | None = None,
    literature_store=None,
    literature_retriever=None,
    rag_top_k: int = 3,
    rag_dense_min_score: float = 0.1,
    online_clients: list | None = None,
    sota_lookup: "SotaLookup | None" = None,
    llm_parser=None,
    network_policy=None,  # NetworkPolicy | None — defer import for cycles
    paper_cache=None,  # PaperCache | None — Phase 2 / Task 6
    literature_service=None,  # LiteratureService | None — Phase 4 / Task 6
) -> dict[str, Any]:
    """Ground a research objective into an execution plan.

    Uses LLM to select the best skill, then retrieves relevant literature
    and baselines from the local store. If ``sota_lookup`` is supplied,
    the function also queries it for a published target metric and emits
    the result on the returned dict under the ``sota_target`` key (as
    produced by ``SotaTarget.to_dict()``). Callers with a session state
    (e.g. ``ResearchDirector.advance``) are responsible for copying the
    payload onto ``state.objective`` — grounding itself no longer mutates
    target fields on the passed objective.

    When ``objective.dataset_hint`` is empty the function still extracts a
    dataset from the question and writes it back onto the passed
    ``objective`` (legacy behaviour preserved for single-caller uses) AND
    emits the inferred value on the returned dict as
    ``dataset_hint_inferred`` so the director can mirror it onto state.

    Returns a dict with at least:
      - selected_skill: str or "" if no match
      - route: "skill" | "free"
      - reason: str (LLM's explanation)
      - papers: list[dict] (retrieved paper summaries)
      - baselines: list[dict] (relevant baselines)
      - citations: list[dict] (paper references for the execution brief)
      - task_profile: dict (TaskProfile.to_dict() honoring selected_skill)
      - dataset_hint_source: "explicit" | "literal_regex" | "semantic_inference"
                            | "path_extract" | "" (audit addition)

    Optional keys (present only when applicable):
      - dataset_hint_inferred: str — inferred dataset name when the caller
        left ``objective.dataset_hint`` empty.
      - task_type_inferred: str — coarse task type extracted from the
        question by ``extract_dataset_and_task``.
      - sota_target: dict — the ``SotaTarget.to_dict()`` payload for the
        published target metric discovered via ``sota_lookup``.

    Plan-2026-04-29 grounding-routing-repair: ``ground_objective`` is now
    referentially pure WRT ``objective`` — it does NOT mutate
    ``objective.dataset_hint``. Callers should copy
    ``grounding["dataset_hint_inferred"]`` onto state themselves
    (director.py:85-87 owns this).
    """
    grounding: dict[str, Any] = {"selected_skill": "", "route": "free", "reason": ""}

    # Plan-2026-04-29 literature-acquisition Phase 1 / Task 8: build a
    # NetworkPolicy + NetworkStatus once and let each leg record itself.
    from ..runtime.network_policy import (
        NetworkLegStatus, NetworkPolicy, NetworkStatus,
    )
    policy = network_policy or NetworkPolicy()
    network_status = NetworkStatus(policy=policy)

    # 1. Dataset hint extraction (cheap regex+semantic, no LLM needed for
    #    the common case). Always run so we capture both the inferred
    #    dataset AND the inferred coarse task_type — even when the user
    #    supplied an explicit dataset_hint, we still want _task_from_q.
    inferred_dataset, _task_from_q = extract_dataset_and_task(
        objective.question,
        llm_parser=llm_parser,
        preferred_skill=objective.preferred_skill,
    )
    if (objective.dataset_hint or "").strip():
        effective_dataset_hint = objective.dataset_hint
        grounding["dataset_hint_source"] = "explicit"
    elif inferred_dataset:
        grounding["dataset_hint_inferred"] = inferred_dataset
        # Decide source by inspecting the question.
        question_lower = objective.question.lower()
        dataset_lower = inferred_dataset.lower()
        if "/" in objective.question and dataset_lower in question_lower:
            grounding["dataset_hint_source"] = "path_extract"
        elif dataset_lower in question_lower:
            grounding["dataset_hint_source"] = "literal_regex"
        else:
            grounding["dataset_hint_source"] = "semantic_inference"
        effective_dataset_hint = inferred_dataset
    else:
        grounding["dataset_hint_source"] = ""
        effective_dataset_hint = ""
    if _task_from_q:
        grounding["task_type_inferred"] = _task_from_q

    # 2. Heuristic task profile (no LLM context yet) — feeds the LLM
    #    skill selection prompt as a hint AND seeds the fallback chain
    #    so we don't recompute the profile twice.
    heuristic_profile = infer_task_profile(
        objective.question,
        selected_skill="",
        dataset_hint=effective_dataset_hint,
    )
    task_profile_llm_parser = _resolve_task_profile_llm_parser(llm_parser, llm_config)
    task_profile_enrichment = extract_task_profile_enrichment(
        objective.question,
        heuristic_profile,
        llm_parser=task_profile_llm_parser,
    )
    enriched_profile, task_profile_sources = merge_task_profile_enrichment(
        heuristic_profile,
        task_profile_enrichment,
        allow_task_shape_override=not bool((objective.preferred_skill or "").strip()),
    )
    if not task_profile_enrichment.is_empty():
        grounding["llm_task_profile"] = task_profile_enrichment.to_dict()
    if task_profile_sources:
        grounding["task_profile_sources"] = dict(task_profile_sources)
    if task_profile_sources.get("dataset_hint_candidates"):
        grounding["dataset_hint_candidates"] = list(
            task_profile_sources["dataset_hint_candidates"]
        )
    heuristic_profile = enriched_profile

    # 3. Skill selection.
    available = _load_available_skills()
    available_names = [s["name"] for s in available]

    preferred = (objective.preferred_skill or "").strip()
    if preferred:
        # Plan-2026-04-29 grounding-routing-repair Task 4: validate
        # explicit preferred_skill against the registry. A typo like
        # ``mil_classfication`` must NOT pass through unchallenged —
        # it would tell the agent ``skill_browser load mil_classfication``
        # and waste an iteration.
        if preferred in available_names:
            logger.info(f"Grounding: using preferred skill '{preferred}'")
            grounding["selected_skill"] = preferred
            grounding["route"] = "skill"
            grounding["reason"] = "user-specified"
        else:
            candidate, fallback_source = _resolve_skill_fallback(
                objective, available_names, profile=heuristic_profile,
            )
            if candidate:
                logger.warning(
                    f"Grounding: unknown preferred_skill '{preferred}', "
                    f"using {fallback_source} → '{candidate}'"
                )
                grounding["selected_skill"] = candidate
                grounding["route"] = "skill"
                grounding["reason"] = (
                    f"unknown_preferred_skill:{preferred}; {fallback_source}"
                )
            else:
                logger.warning(
                    f"Grounding: unknown preferred_skill '{preferred}', "
                    f"falling through to free mode"
                )
                grounding["reason"] = f"unknown_preferred_skill:{preferred}"
    elif available:
        try:
            result = _llm_select_skill(
                objective, available,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
                llm_base_url=llm_base_url,
                llm_config=llm_config,
                profile=heuristic_profile,
            )
            selected = result.get("selected_skill", "none")
            reason = result.get("reason", "")

            if selected and selected != "none" and selected in available_names:
                logger.info(f"Grounding: LLM selected skill '{selected}' — {reason}")
                grounding["selected_skill"] = selected
                grounding["route"] = "skill"
                grounding["reason"] = reason
            else:
                if selected and selected not in available_names:
                    logger.warning(
                        f"LLM selected unknown skill '{selected}', "
                        f"trying preferred_skill + heuristic fallback"
                    )
                else:
                    logger.info(
                        f"Grounding: LLM returned no skill ({reason}), "
                        f"trying preferred_skill + heuristic"
                    )
                candidate, fallback_source = _resolve_skill_fallback(
                    objective, available_names, profile=heuristic_profile,
                )
                if candidate:
                    logger.info(
                        f"Grounding: {fallback_source} selected skill '{candidate}'"
                    )
                    grounding["selected_skill"] = candidate
                    grounding["route"] = "skill"
                    grounding["reason"] = (
                        f"{fallback_source}: llm_returned={selected!r}, "
                        f"reason={reason!r}"
                    )
                else:
                    grounding["reason"] = reason
        except Exception as e:
            logger.warning(
                f"LLM skill selection failed: {e}, "
                f"trying preferred_skill + heuristic fallback"
            )
            candidate, fallback_source = _resolve_skill_fallback(
                objective, available_names, profile=heuristic_profile,
            )
            if candidate:
                logger.info(
                    f"Grounding: {fallback_source} selected skill '{candidate}' after LLM error"
                )
                grounding["selected_skill"] = candidate
                grounding["route"] = "skill"
                grounding["reason"] = (
                    f"{fallback_source}: llm_error={type(e).__name__}"
                )
            else:
                grounding["reason"] = f"llm_error: {e}"

    # 4. Final task_profile with selected_skill applied. This is what
    #    the acquisition layer reads — task_type honors the routed skill.
    selected_skill = (
        grounding.get("selected_skill", "") or objective.preferred_skill
    )
    profile = infer_task_profile(
        objective.question,
        selected_skill=selected_skill,
        dataset_hint=effective_dataset_hint,
    )
    profile, final_sources = merge_task_profile_enrichment(
        profile,
        task_profile_enrichment,
        allow_task_shape_override=not bool(
            (selected_skill or "").strip()
            or (objective.preferred_skill or "").strip()
        ),
    )
    if final_sources:
        merged_sources = dict(grounding.get("task_profile_sources") or {})
        merged_sources.update(final_sources)
        grounding["task_profile_sources"] = merged_sources
    if final_sources.get("dataset_hint_candidates"):
        grounding["dataset_hint_candidates"] = list(
            final_sources["dataset_hint_candidates"]
        )
    grounding["task_profile"] = profile.to_dict()
    organ = profile.organ or None

    # 5. Coarse task_type — single source of truth for retrieval/RAG/SOTA.
    task_type = _infer_task_type(
        objective,
        selected_skill=selected_skill,
        task_hint=_task_from_q,
    )

    # 6. Literature retrieval — receives organ/task filters now (T6) + policy (T8).
    grounding.update(
        _retrieve_literature(
            objective, literature_store,
            online_clients=online_clients or [],
            organ=organ, task_type=task_type,
            dataset_hint=effective_dataset_hint,
            network_policy=policy,
            paper_cache=paper_cache,
            literature_service=literature_service,
        )
    )
    # Record paper leg status. ``_retrieve_literature`` puts it on
    # the result dict under a private key for unification.
    paper_leg = grounding.pop("_paper_leg_status", None)
    if paper_leg is not None:
        network_status.record("papers", paper_leg)
    else:
        network_status.record(
            "papers",
            NetworkLegStatus(
                leg="papers",
                state="disabled" if literature_store is None else "not_invoked",
            ),
        )

    # 7. Passage-level RAG retrieval. Plan-2026-04-29 P0-2 + T6:
    #    surface rag_status AND pass organ/task filters through.
    # Plan-2026-04-29 literature-acquisition Phase 1 / Task 8: re-raise
    # NetworkUnavailableError so fail-hard policy aborts cleanly.
    # Phase 4b: prefer service-bound passage retriever when wired.
    from ..runtime.network_policy import NetworkUnavailableError
    effective_passage_retriever = literature_retriever
    if effective_passage_retriever is None and literature_service is not None:
        effective_passage_retriever = getattr(
            literature_service, "_passages", None,
        )
    if effective_passage_retriever is not None:
        try:
            passages = effective_passage_retriever.retrieve_passages(
                query=objective.question,
                top_k=rag_top_k,
                organ=organ,
                task_type=task_type,
                dense_min_score=rag_dense_min_score,
            )
            grounding["passages"] = [
                {
                    "paper_id": p.paper_id,
                    "chunk_id": p.chunk_id,
                    "text": p.text[:300],
                    "score": round(p.score, 4),
                    "page": p.page,
                    "section": p.section,
                }
                for p in passages
            ]
            grounding["rag_status"] = getattr(
                effective_passage_retriever, "last_status", "unknown",
            )
            dense_err = getattr(effective_passage_retriever, "last_dense_error", "")
            sparse_err = getattr(effective_passage_retriever, "last_sparse_error", "")
            if dense_err:
                grounding["rag_dense_error"] = dense_err
            if sparse_err:
                grounding["rag_sparse_error"] = sparse_err
            rag_leg = getattr(effective_passage_retriever, "last_network_status", None)
            if rag_leg is not None:
                network_status.record("rag_dense", rag_leg)
        except NetworkUnavailableError:
            raise
        except Exception as e:
            logger.warning(f"Passage retrieval failed: {e}")
            grounding.setdefault("passages", [])
            grounding["rag_status"] = "error"
            grounding["rag_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            network_status.record(
                "rag_dense",
                NetworkLegStatus(
                    leg="rag_dense", state="error",
                    error=f"{type(e).__name__}: {str(e)[:200]}",
                ),
            )
    else:
        grounding.setdefault("passages", [])
        grounding.setdefault("rag_status", "disabled")
        network_status.record(
            "rag_dense", NetworkLegStatus(leg="rag_dense", state="disabled"),
        )

    # 8. SOTA lookup (uses derived task_type from selected_skill).
    # Phase 4b: prefer service-bound sota_lookup when wired.
    effective_sota_lookup = sota_lookup
    if effective_sota_lookup is None and literature_service is not None:
        effective_sota_lookup = getattr(literature_service, "_sota", None)
    if effective_sota_lookup is None:
        grounding["sota_lookup_status"] = "disabled"
        network_status.record(
            "sota", NetworkLegStatus(leg="sota", state="disabled"),
        )
    elif not effective_dataset_hint:
        grounding["sota_lookup_status"] = "no_dataset_hint"
        network_status.record(
            "sota", NetworkLegStatus(leg="sota", state="not_invoked"),
        )
    else:
        lookup_task_type = task_type or "classification"
        try:
            target = effective_sota_lookup.lookup(
                dataset=effective_dataset_hint,
                task_type=lookup_task_type,
                metric=objective.success_metric,
            )
        except NetworkUnavailableError:
            raise
        except Exception as e:
            logger.warning("SotaLookup raised: %s", e)
            target = None
            grounding["sota_lookup_status"] = "error"
            network_status.record(
                "sota",
                NetworkLegStatus(
                    leg="sota", state="error",
                    error=f"{type(e).__name__}: {str(e)[:200]}",
                ),
            )
        else:
            grounding["sota_lookup_status"] = getattr(
                effective_sota_lookup, "last_status", "unknown"
            )
            sota_leg = getattr(effective_sota_lookup, "last_network_status", None)
            if sota_leg is not None:
                network_status.record("sota", sota_leg)
        if target is not None:
            grounding["sota_target"] = target.to_dict()
            logger.info(
                "SotaLookup: target=%.4f from %s (%s, %s)",
                target.metric_value, target.source, target.paper_id,
                target.confidence,
            )

    grounding["network_status"] = network_status.to_dict()
    # Plan-2026-04-29 literature-acquisition Phase 4 / Task 6: the
    # service itself is NOT placed on the grounding dict because the
    # dict is persisted via Pydantic and a LiteratureService instance
    # isn't serializable. Downstream consumers reach the service via
    # ``director.literature_service`` (for live access) or rebuild it
    # from state on resume.
    return grounding


def _retrieve_literature(
    objective: ResearchObjective,
    literature_store,
    online_clients: list | None = None,
    *,
    organ: str | None = None,
    task_type: str | None = None,
    dataset_hint: str = "",
    network_policy=None,  # NetworkPolicy | None
    paper_cache=None,  # PaperCache | None — Phase 2 / Task 6
    literature_service=None,  # LiteratureService | None — Phase 4b
) -> dict[str, Any]:
    """Retrieve papers and baselines from literature store, with optional online fill.

    Plan-2026-04-29 P1-7: emits structured ``online_literature_status`` so
    reviewers can tell whether online clients contributed papers, failed,
    or were never invoked. Local count is reported separately.

    Plan-2026-04-29 grounding-routing-repair Task 6: ``organ``,
    ``task_type``, and ``dataset_hint`` are now passed in by
    ``ground_objective`` (single source of truth) instead of being
    re-inferred per call.

    Plan-2026-04-29 literature-acquisition Phase 1 / Task 8:
    ``network_policy`` controls whether online clients fire and how
    failures are handled. The retriever's last NetworkLegStatus is
    surfaced as ``result["_paper_leg_status"]`` for the caller to
    record in the unified ``network_status`` block.

    Plan-2026-04-29 literature-acquisition Phase 4b: when
    ``literature_service`` is wired, paper-search + baselines go
    through the service-bound retriever (one instance per session)
    instead of constructing a fresh ``LiteratureRetriever`` inline.
    """
    from ..runtime.network_policy import NetworkUnavailableError
    result: dict[str, Any] = {
        "papers": [], "baselines": [], "citations": [],
        "local_paper_count": 0,
        "online_literature_status": "disabled" if not online_clients else "not_invoked",
        "online_literature_providers": [],
    }

    # Phase 4b: prefer the service-bound retriever when available so
    # we don't construct a duplicate inline. A service that wasn't given
    # a literature_retriever still falls back to inline construction.
    service_retriever = None
    if literature_service is not None:
        service_retriever = getattr(literature_service, "_literature", None)

    if service_retriever is None and literature_store is None:
        # Online clients only fire as fallback to local; without a store
        # AND without a service-supplied retriever, there's nothing to
        # call.
        result["online_literature_status"] = "disabled"
        return result

    try:
        retriever = service_retriever
        if retriever is None:
            from ..literature.retriever import LiteratureRetriever
            # Plan-2026-04-29 literature-acquisition Phase 1 / Task 8:
            # forward NetworkPolicy so paper search honors the same gates
            # as the rest of the literature stack.
            retriever = LiteratureRetriever(
                literature_store,
                api_clients=online_clients or [],
                policy=network_policy,
                paper_cache=paper_cache,
            )

        # Retrieve relevant papers (T6: pass organ + task filters).
        papers = retriever.retrieve(
            query=objective.question,
            organ=organ,
            task_type=task_type,
            top_k=5,
        )
        result["papers"] = [
            {"paper_id": p.paper_id, "title": p.title, "year": p.year,
             "source": p.source, "url": p.url}
            for p in papers
        ]

        # Extract baselines using the already-derived task_type so the
        # store filters the same way grounding does. ``dataset_hint``
        # comes from the caller's effective hint (explicit user input or
        # inferred), NOT from a possibly-mutated ``objective``.
        effective_dataset = (dataset_hint or "").strip()
        baselines = retriever.get_baselines_for_task(
            query=objective.question,
            dataset=effective_dataset if effective_dataset else None,
            task_type=task_type,
            top_k=5,
        )
        result["baselines"] = [b.to_dict() for b in baselines]

        # Track citations
        result["citations"] = [
            {"paper_id": p.paper_id, "title": p.title}
            for p in papers
        ]

        # Plan-2026-04-29 P1-7: surface online vs local provenance.
        online_stat = getattr(retriever, "last_online_status", {}) or {}
        result["local_paper_count"] = int(online_stat.get("local_count", 0))
        provider_records = list(online_stat.get("providers", []) or [])
        result["online_literature_providers"] = provider_records

        if not online_stat.get("enabled", False):
            result["online_literature_status"] = "disabled"
        elif not provider_records:
            # Online enabled but never invoked (e.g. local already filled top_k).
            result["online_literature_status"] = "not_invoked"
        else:
            errors = [p for p in provider_records if p.get("error")]
            merged = sum(int(p.get("merged", 0) or 0) for p in provider_records)
            if errors and merged == 0:
                result["online_literature_status"] = "error"
                result["online_literature_error"] = errors[0]["error"]
                result["online_literature_provider"] = errors[0]["provider"]
            elif merged == 0:
                result["online_literature_status"] = "no_results"
                result["online_literature_provider"] = provider_records[0]["provider"]
            else:
                result["online_literature_status"] = "ok"
                result["online_literature_count"] = merged
                # Pick the provider that contributed the most papers as the
                # canonical attribution.
                top = max(provider_records, key=lambda p: int(p.get("merged", 0) or 0))
                result["online_literature_provider"] = top["provider"]

        if baselines:
            best = baselines[0]
            logger.info(
                f"Literature: found {len(papers)} papers "
                f"(local={result['local_paper_count']}, "
                f"online_status={result['online_literature_status']}), "
                f"best baseline: {best.method} {best.metric_name}={best.metric_value} on {best.dataset}"
            )
        else:
            logger.info(
                f"Literature: found {len(papers)} papers "
                f"(local={result['local_paper_count']}, "
                f"online_status={result['online_literature_status']}), "
                f"no baselines extracted"
            )

        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 8:
        # surface the retriever's NetworkLegStatus so ground_objective
        # can record it in the unified network_status object.
        leg_status = getattr(retriever, "last_network_status", None)
        if leg_status is not None:
            result["_paper_leg_status"] = leg_status

    except NetworkUnavailableError:
        # fail-hard: bubble up so the caller can abort the session.
        raise
    except Exception as e:
        logger.warning(f"Literature retrieval failed: {e}")
        result["online_literature_status"] = "error"
        result["online_literature_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    return result


def _infer_task_type(
    objective: ResearchObjective,
    *,
    selected_skill: str = "",
    task_hint: str = "",
) -> str | None:
    """Infer a coarse task type for literature/RAG/SOTA filtering.

    Plan-2026-04-29 grounding-routing-repair Task 3: priority is
    selected_skill → explicit task_hint (from objective_extractor) →
    objective.preferred_skill → text fallback. A successful skill or
    hint short-circuits the text scan, so a default ``success_metric=
    "auc"`` no longer misroutes a survival/segmentation task to
    ``classification``.

    The text fallback uses word-boundary regex for short tokens (``mil``)
    so it doesn't match inside unrelated words like ``familial``.
    """
    # 1. Final selected skill wins — single source of truth.
    skill_task = _coarse_task_type_from_skill(selected_skill)
    if skill_task:
        return skill_task

    # 2. Explicit task hint from objective_extractor (regex pass over
    #    the question, e.g. "segment masks and report Dice" → "segmentation").
    hint = (task_hint or "").strip().lower()
    if hint:
        if hint in {"classification", "segmentation", "survival", "feature_extraction"}:
            return hint
        if hint == "survival_analysis":
            return "survival"

    # 3. Pre-existing preferred_skill.
    preferred_task = _coarse_task_type_from_skill(objective.preferred_skill)
    if preferred_task:
        return preferred_task

    # 4. Text fallback — preference order specific → general.
    text = " ".join([
        objective.question,
        objective.success_metric,
        objective.preferred_skill,
    ]).lower()

    if "survival" in text or "c-index" in text or "cindex" in text:
        return "survival"
    if "segment" in text or "dice" in text or "iou" in text:
        return "segmentation"
    if "feature extraction" in text or "extract features" in text or "foundation model" in text or "extractor" in text:
        return "feature_extraction"

    # ``mil`` word-boundary so "familial"/"premise"/etc don't false-positive.
    short_classification_tokens = {"mil"}
    for token in ["auc", "accuracy", "classification", "classify", "mil"]:
        if token in short_classification_tokens:
            if re.search(rf"\b{re.escape(token)}\b", text):
                return "classification"
        elif token in text:
            return "classification"
    return None
