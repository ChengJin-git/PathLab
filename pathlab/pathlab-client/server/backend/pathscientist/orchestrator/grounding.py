"""Phase 1 grounding: LLM-based skill selection and task routing.

Uses the agent's LLM to choose the best matching skill from the registry
based on the user's research objective. Falls back to "free" mode if no
skill matches or if the LLM/registry is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ..config import (
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_required_llm_model,
)
from ..dataset.task_profile import infer_task_profile
from ..orchestrator.types import ResearchObjective
from .objective_extractor import extract_dataset_and_task

if TYPE_CHECKING:
    from ..literature.sota_lookup import SotaLookup

logger = logging.getLogger(__name__)


def _build_skill_selection_prompt(objective: ResearchObjective, skills: list[dict]) -> str:
    """Build a prompt asking the LLM to select the best skill."""
    skill_list = "\n".join(
        f"- **{s['name']}**: {s['description']}"
        for s in skills
    )
    return f"""You are a research task router for computational pathology.

Given the following research objective, select the most appropriate skill template.
If none of the skills match, respond with "none".

## Research Objective
{objective.question}

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
) -> dict[str, str]:
    """Use LLM to select the best skill for the objective."""
    from pydantic import SecretStr
    from openhands.sdk.llm import LLM

    # Build LLM
    llm_kwargs: dict[str, Any] = {}
    llm_kwargs["model"] = resolve_required_llm_model(
        llm_model,
        component="skill selection",
    )
    api_key = resolve_llm_api_key(llm_api_key)
    if api_key:
        llm_kwargs["api_key"] = SecretStr(api_key)
    base_url = resolve_llm_base_url(llm_base_url)
    if base_url:
        llm_kwargs["base_url"] = base_url
    llm_kwargs["temperature"] = 0.0
    llm_kwargs["usage_id"] = "grounding"

    llm = LLM(**llm_kwargs)

    prompt = _build_skill_selection_prompt(objective, skills)

    from openhands.sdk.llm import Message, TextContent
    response = llm.completion(
        messages=[Message(role="user", content=[TextContent(text=prompt)])],
    )

    # Parse response
    text = response.message.content[0].text.strip()
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


def ground_objective(
    objective: ResearchObjective,
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    literature_store=None,
    literature_retriever=None,
    rag_top_k: int = 3,
    rag_dense_min_score: float = 0.1,
    online_clients: list | None = None,
    sota_lookup: "SotaLookup | None" = None,
    llm_parser=None,
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

    Optional keys (present only when applicable):
      - dataset_hint_inferred: str — inferred dataset name when the caller
        left ``objective.dataset_hint`` empty.
      - sota_target: dict — the ``SotaTarget.to_dict()`` payload for the
        published target metric discovered via ``sota_lookup``.
    """
    grounding: dict[str, Any] = {"selected_skill": "", "route": "free", "reason": ""}

    # 1. Explicit preferred skill — skip LLM
    if objective.preferred_skill:
        logger.info(f"Grounding: using preferred skill '{objective.preferred_skill}'")
        grounding = {"selected_skill": objective.preferred_skill, "route": "skill", "reason": "user-specified"}
    else:
        # 2. Load skill registry
        try:
            from ..domain.skills import registry
            registry.load_all()
            available = [
                {"name": s.name, "description": s.description}
                for s in registry.list_skills()
            ]
        except Exception as e:
            logger.warning(f"Skill registry unavailable: {e}")
            available = []

        # 3. Ask LLM to choose
        if available:
            try:
                result = _llm_select_skill(
                    objective, available,
                    llm_model=llm_model,
                    llm_api_key=llm_api_key,
                    llm_base_url=llm_base_url,
                )
                selected = result.get("selected_skill", "none")
                reason = result.get("reason", "")

                if selected and selected != "none":
                    available_names = [s["name"] for s in available]
                    if selected in available_names:
                        logger.info(f"Grounding: LLM selected skill '{selected}' — {reason}")
                        grounding = {"selected_skill": selected, "route": "skill", "reason": reason}
                    else:
                        logger.warning(f"LLM selected unknown skill '{selected}', falling back to free mode")
                        grounding["reason"] = reason
                else:
                    logger.info(f"Grounding: no skill matched — {reason}")
                    grounding["reason"] = reason
            except Exception as e:
                logger.warning(f"LLM skill selection failed: {e}, falling back to free mode")
                grounding["reason"] = f"llm_error: {e}"

    # 4. Literature retrieval (always runs, independent of skill selection)
    grounding.update(_retrieve_literature(objective, literature_store, online_clients=online_clients or []))

    # 5. Passage-level RAG retrieval (when available)
    if literature_retriever is not None:
        try:
            task_type = _infer_task_type(objective)
            passages = literature_retriever.retrieve_passages(
                query=objective.question,
                top_k=rag_top_k,
                organ=None,
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
        except Exception as e:
            logger.warning(f"Passage retrieval failed: {e}")
            grounding.setdefault("passages", [])
    else:
        grounding.setdefault("passages", [])

    # 6. Fill dataset_hint from the question if the caller did not supply one.
    #    Emit the inferred value in the returned dict so callers holding a
    #    session state (e.g. the director) can mirror it onto state.objective.
    #    We also write it back onto the passed objective for legacy callers
    #    that don't route through state.
    if not objective.dataset_hint:
        dataset, _task_from_q = extract_dataset_and_task(
            objective.question,
            llm_parser=llm_parser,
            preferred_skill=objective.preferred_skill,
        )
        if dataset:
            grounding["dataset_hint_inferred"] = dataset
            objective.dataset_hint = dataset

    # 6.5. Task profile (heuristic) — used by acquisition layer.
    profile = infer_task_profile(
        objective.question,
        selected_skill=grounding.get("selected_skill", "") or objective.preferred_skill,
        dataset_hint=objective.dataset_hint,
    )
    grounding["task_profile"] = profile.to_dict()

    # 7. Query SotaLookup for a real target when possible. Emit the target
    #    payload on the returned dict rather than mutating target fields on
    #    the objective — the director owns copy-to-state.
    if sota_lookup is not None and objective.dataset_hint:
        task_type = (
            _infer_task_type(objective)
            or "classification"
        )
        try:
            target = sota_lookup.lookup(
                dataset=objective.dataset_hint,
                task_type=task_type,
                metric=objective.success_metric,
            )
        except Exception as e:
            logger.warning("SotaLookup raised: %s", e)
            target = None
        if target is not None:
            grounding["sota_target"] = target.to_dict()
            logger.info(
                "SotaLookup: target=%.4f from %s (%s, %s)",
                target.metric_value, target.source, target.paper_id,
                target.confidence,
            )

    return grounding


def _retrieve_literature(
    objective: ResearchObjective,
    literature_store,
    online_clients: list | None = None,
) -> dict[str, Any]:
    """Retrieve papers and baselines from literature store, with optional online fill."""
    result: dict[str, Any] = {"papers": [], "baselines": [], "citations": []}

    if literature_store is None:
        return result

    try:
        from ..literature.retriever import LiteratureRetriever
        retriever = LiteratureRetriever(literature_store, api_clients=online_clients or [])

        # Retrieve relevant papers
        papers = retriever.retrieve(
            query=objective.question,
            top_k=5,
        )
        result["papers"] = [
            {"paper_id": p.paper_id, "title": p.title, "year": p.year,
             "source": p.source, "url": p.url}
            for p in papers
        ]

        # Extract baselines
        dataset_hint = objective.dataset_hint or ""
        task_type = _infer_task_type(objective)
        baselines = retriever.get_baselines_for_task(
            query=objective.question,
            dataset=dataset_hint if dataset_hint else None,
            task_type=task_type,
            top_k=5,
        )
        result["baselines"] = [b.to_dict() for b in baselines]

        # Track citations
        result["citations"] = [
            {"paper_id": p.paper_id, "title": p.title}
            for p in papers
        ]

        if baselines:
            best = baselines[0]
            logger.info(
                f"Literature: found {len(papers)} papers, "
                f"best baseline: {best.method} {best.metric_name}={best.metric_value} on {best.dataset}"
            )
        else:
            logger.info(f"Literature: found {len(papers)} papers, no baselines extracted")

    except Exception as e:
        logger.warning(f"Literature retrieval failed: {e}")

    return result


def _infer_task_type(objective: ResearchObjective) -> str | None:
    """Infer a coarse task type from the objective when explicit state is missing."""
    skill = objective.preferred_skill.lower()
    if "survival" in skill:
        return "survival"
    if "segment" in skill:
        return "segmentation"
    if "classification" in skill or "mil" in skill:
        return "classification"
    if "feature_extraction" in skill or "feature-extraction" in skill:
        return "feature_extraction"

    text = " ".join([
        objective.question,
        objective.success_metric,
        objective.preferred_skill,
    ]).lower()

    if "survival" in text or "c-index" in text or "cindex" in text:
        return "survival"
    if "segment" in text or "dice" in text or "iou" in text:
        return "segmentation"
    if any(token in text for token in ["auc", "accuracy", "classification", "classify", "mil"]):
        return "classification"
    if "feature" in text or "foundation model" in text or "extractor" in text:
        return "feature_extraction"
    return None
