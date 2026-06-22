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
from pathlib import Path
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
# Plan-2026-05-14 stage3 P1-9: previously these were three function-local
# imports stamped "deferred for cycle avoidance" — verified no cycle
# exists, so promote to module top. Cuts ~50ms/call cold-cache test
# overhead and removes the latent NameError class of bug from forgetting
# the import in a new branch.
from ..runtime.network_policy import (
    NetworkLegStatus,
    NetworkPolicy,
    NetworkStatus,
    NetworkUnavailableError,
)
from .objective_extractor import (
    TASK_KEYWORD_RULES,
    extract_dataset_and_task,
)

if TYPE_CHECKING:
    from ..literature.sota_lookup import SotaLookup

logger = logging.getLogger(__name__)


# Plan-2026-04-29 grounding-routing-repair Task 3: canonical mapping from
# selected_skill (the high-confidence final routing decision) to coarse
# task_type used by literature/RAG/SOTA. Single source of truth so RAG
# task_type, baseline task_type, and SOTA task_type can never silently
# disagree with the chosen skill.
# Plan-2026-05-14 stage3 P2-6: the canonical coarse_task_type for each
# skill now lives on the skill's YAML (``coarse_task_type:`` field). This
# hardcoded map remains as a fallback for legacy skills that haven't
# been migrated and for the rare case where the registry import fails.
_SKILL_TO_COARSE_TASK_FALLBACK: dict[str, str] = {
    "patch_classification": "classification",
    "mil_classification": "classification",
    "patch_segmentation": "segmentation",
    "survival_analysis": "survival",
    "feature_extraction": "feature_extraction",
}


def _coarse_task_type_from_skill(skill: str) -> str:
    """Return the coarse task category for a skill name.

    Plan-2026-05-14 stage3 P2-6: prefer the YAML ``coarse_task_type``
    field on the registered skill; fall back to the hardcoded map only
    when the skill isn't registered or the field isn't set. The fallback
    keeps tests that mock the registry working.
    """
    key = (skill or "").strip().lower()
    if not key:
        return ""
    try:
        from ..domain.skills import registry

        registry.load_all()
        for s in registry.list_skills():
            if (s.name or "").strip().lower() == key:
                declared = (getattr(s, "coarse_task_type", "") or "").strip()
                if declared:
                    return declared
                break
    except Exception:
        pass
    return _SKILL_TO_COARSE_TASK_FALLBACK.get(key, "")


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
    heuristic profile is supplied we surface a weak candidate and evidence
    as a hint. Pre-fix the LLM saw only the question and the skill list —
    CRC-MSI prompts hit ``selected_skill="none"`` because there was no
    anchor. With evidence the LLM can confirm or explicitly override.
    """
    skill_list = "\n".join(
        f"- **{s['name']}**: {s['description']}"
        for s in skills
    )
    hint_block = ""
    if profile is not None:
        bits = []
        if profile.preferred_skill:
            bits.append(
                f"candidate={profile.preferred_skill}, "
                f"evidence={_heuristic_profile_evidence(profile)}"
            )
        if profile.organ:
            bits.append(f"organ={profile.organ}")
        if profile.prediction_target:
            bits.append(f"target={profile.prediction_target}")
        hint_block = (
            "\n\n## Heuristic Candidates (weak evidence; you may override)\n"
            + ", ".join(bits)
        )
    return f"""You are a research task router for computational pathology.

Given the following research objective, select:

1. ``selected_skill`` — the user's ULTIMATE goal skill (or "none" if no
   skill matches). For "train a Gleason MIL classifier" the ultimate goal
   is ``mil_classification`` even if the user wants to stop earlier.

2. ``stop_after_skill`` — the skill the user wants the pipeline to STOP
   AFTER, when they explicitly say so (e.g. "but don't train",
   "只跑特征提取", "no training", "stop after feature extraction"). Set
   to "" (empty string) when the user wants a full run. This is INDEPENDENT
   of selected_skill: a user can want ``selected_skill=mil_classification``
   AND ``stop_after_skill=feature_extraction`` in the same prompt.

   Common stop boundaries: ``acquisition`` (only data download/prep),
   ``feature_extraction`` (data + features, no training).

## Research Objective
{objective.question}{hint_block}

## Available Skills
{skill_list}

Respond with ONLY a JSON object, no other text. Required keys:
{{"selected_skill": "<skill_name or none>",
  "stop_after_skill": "<acquisition|feature_extraction|skill_name|>",
  "reason": "<one sentence why, including stop intent if any>"}}"""


def _heuristic_profile_evidence(profile: TaskProfile) -> list[str]:
    """Return compact evidence strings for a heuristic skill candidate."""
    evidence: list[str] = []
    if profile.task_type:
        evidence.append(f"task_type:{profile.task_type}")
    if profile.asset_level:
        evidence.append(f"asset_level:{profile.asset_level}")
    if profile.input_modality:
        evidence.append(f"input_modality:{profile.input_modality}")
    if profile.prediction_target:
        evidence.append(f"target:{profile.prediction_target}")
    if profile.organ:
        evidence.append(f"organ:{profile.organ}")
    return evidence


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object from LLM text, tolerating fenced/explained output.

    Plan-2026-05-14 stage3 P1-3:
    1. Previously looped over every ``{`` char in every candidate — for
       an N-char response with K open braces that's O(K·N) raw_decode
       calls. Now we snap to the first ``{`` per candidate and let
       raw_decode consume from there: O(N) worst case, same coverage
       for real LLM outputs.
    2. ``<think>...</think>`` was stripped via ``split("</think>")[-1]``,
       so an unclosed ``<think>`` tag (model truncated mid-thought) ate
       the JSON answer. ``re.sub`` only removes closed blocks and leaves
       unclosed ones alone.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)

    candidates: list[str] = []
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:json)?\s*(.*?)```",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    candidates.append(cleaned)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        # Skip past any prose preamble — raw_decode chokes on it.
        idx = candidate.find("{")
        if idx < 0:
            continue
        try:
            parsed, _ = decoder.raw_decode(candidate[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _llm_select_skill(
    objective: ResearchObjective,
    skills: list[dict],
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    llm_config: PathScientistConfig | None = None,
    profile: TaskProfile | None = None,
    temperature: float | None = None,
) -> dict[str, str]:
    """Use LLM to select the best skill for the objective.

    Plan-2026-05-14 stage3 P2-3: ``temperature`` is now configurable.
    Default is taken from ``llm_config.grounding_temperature`` when
    available, else ``0.0`` to preserve deterministic test output.
    Tests can still pin ``temperature=0.0`` explicitly; production
    callers wanting exploration can set the config field.
    """
    config = make_llm_config(
        config=llm_config,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
    )
    if temperature is None:
        temperature = float(
            getattr(llm_config, "grounding_temperature", 0.0) or 0.0
        )
    llm = build_chat_llm(
        config,
        component="skill selection",
        usage_id="grounding",
        temperature=temperature,
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
    result = _extract_first_json_object(text)
    if result is not None:
        selected = str(result.get("selected_skill", "none") or "none").strip()
        selected_lower = selected.lower()
        if selected_lower in {"none", "null"}:
            selected = "none"
        else:
            selected = selected_lower
        # 2026-05-10 stop-after refactor: parse stop_after_skill alongside
        # selected_skill. Backward-compat — older LLM responses without
        # this key surface "" so callers don't need to handle KeyError.
        stop_after_raw = str(
            result.get("stop_after_skill", "") or ""
        ).strip().lower()
        if stop_after_raw in {"null", "none"}:
            stop_after_raw = ""
        return {
            "selected_skill": selected,
            "stop_after_skill": stop_after_raw,
            "reason": str(result.get("reason", "") or ""),
        }

    logger.warning(f"Failed to parse LLM skill selection response: {text[:200]}")
    return {
        "selected_skill": "none",
        "stop_after_skill": "",
        "reason": "parse_error",
    }


def _resolve_skill_fallback(
    objective: ResearchObjective,
    available_names: list[str],
    *,
    profile: TaskProfile,
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
    pass the heuristic profile in to avoid recomputing it.

    Plan-2026-05-14 stage3 P1-2: ``profile`` is now required. The
    previous ``profile=None`` lazy-build branch only fired from tests
    that didn't construct a profile themselves — production callers
    (``ground_objective`` at the three call sites) always pass one.
    Tests now build the profile explicitly via ``infer_task_profile``.

    Returns ``("", "")`` when neither path produces a registered skill.
    """
    candidate = _heuristic_skill_candidate(objective)
    if candidate and candidate in available_names:
        return candidate, "heuristic"
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


# --- Stop-after-skill detection (review 2026-05-10 P0-1) -------------------
#
# Until 2026-05-10 grounding had no field for "user wants to stop the
# pipeline at step X" — selected_skill conflated "ultimate goal" with
# "what to actually run". For session_64561aa7962b the user wrote
#
#   我要训练一个 ... MIL分类模型 ... 完成后开始 featureextraction，但不要开始训练
#
# selected_skill=mil_classification was correct as the ultimate goal, but
# the agent then walked the plan into 9 hours of MIL training. We now
# treat ``stop_after_skill`` as an independent dimension. The LLM picker
# is asked for it explicitly; this heuristic is the safety net used when
# the LLM returns parse_error or forgets the field. Output is the skill
# name to stop after, or "" when the user clearly wants a full run.

# Plan-2026-05-14 stage3 P2-1: ``\bno\b`` alone false-positives on
# "no problem", "no idea", "no worse than". Tighten by requiring "no"
# to be followed (within a few words) by a verb-y stop signal —
# "more", "further", "training", "run", etc. The other tokens
# (don't/skip/stop/disable) carry their own clear stop semantics so
# they stay bare-word.
_NEGATION_EN = re.compile(
    r"\b(?:"
    r"don'?t|do\s+not|"
    r"no\s+(?:more|further|additional|extra|need|"
    r"train(?:ing)?|run(?:ning)?|model(?:s)?)|"
    r"skip|stop|disable|refrain"
    r")\b"
)
_NEGATION_ZH = re.compile(r"不要|不训练|不训|不进行|不开始|不做|不跑|停止|不再")
_TRAIN_EN = re.compile(r"\btrain(?:ing|s)?\b")
# Plan-2026-05-14 stage3 P2-2: bare ``训`` matched inside 训诫 / 训斥 /
# 教训 / 培训 — none of which mean ML "training". Tighten to two-char
# compounds that unambiguously refer to model training.
_TRAIN_ZH = re.compile(r"训练|训完")


def _has_stop_train_signal(text: str) -> bool:
    """Return True iff the text contains a "don't train" intent.

    Uses proximity matching (negation within ~60 chars before "train")
    instead of strict adjacency, so phrasings like "don't run feature
    extraction or training" are caught.
    """
    if not text:
        return False
    # English: negation within 60 chars before train(ing).
    for m in _TRAIN_EN.finditer(text):
        window = text[max(0, m.start() - 60):m.end()]
        if _NEGATION_EN.search(window):
            return True
    # Chinese is denser, but mixed Chinese/English phrases such as
    # "不要开始 feature extraction或训练" need a wider character window.
    for m in _TRAIN_ZH.finditer(text):
        window = text[max(0, m.start() - 40):m.end()]
        if _NEGATION_ZH.search(window):
            return True
    return False


def _last_stop_train_end(text: str) -> int:
    """Return end offset of the last negated train mention, or -1."""
    last = -1
    for m in _TRAIN_EN.finditer(text or ""):
        window = text[max(0, m.start() - 60):m.end()]
        if _NEGATION_EN.search(window):
            last = max(last, m.end())
    for m in _TRAIN_ZH.finditer(text or ""):
        window = text[max(0, m.start() - 40):m.end()]
        if _NEGATION_ZH.search(window):
            last = max(last, m.end())
    return last


def _has_positive_train_signal(text: str) -> bool:
    """Return True when the prompt also contains a non-negated train intent."""
    if not text:
        return False
    for m in _TRAIN_EN.finditer(text):
        window = text[max(0, m.start() - 60):m.end()]
        if not _NEGATION_EN.search(window):
            return True
    for m in _TRAIN_ZH.finditer(text):
        window = text[max(0, m.start() - 40):m.end()]
        if not _NEGATION_ZH.search(window):
            return True
    return False


def _heuristic_stop_after_skill(question: str) -> str:
    """Detect a stop boundary in the user's question. Returns the skill
    name to stop after, or "" when no stop intent is present.

    Independent of skill selection: the user can say "train MIL" (=>
    selected_skill=mil_classification) AND "but stop after feature
    extraction" (=> stop_after_skill=feature_extraction) in the same
    sentence. This function only handles the second axis.
    """
    if not question:
        return ""
    text = question.lower()
    if not _has_stop_train_signal(text):
        # No "don't train" signal anywhere → user wants a full run.
        return ""
    stop_end = _last_stop_train_end(text)
    if stop_end >= 0 and _has_positive_train_signal(text[stop_end:]):
        # Conflicting prompts such as "don't train yet ... then train MIL" are
        # full-run intents with stale setup wording, not acquisition-only tasks.
        return ""

    # Detect a POSITIVE feature-extraction signal first: the user
    # explicitly says they DO want feature extraction done. Once seen,
    # nothing weaker can downgrade the stop boundary to "acquisition".
    fe_mentioned_positive = (
        "feature extraction" in text
        or "extract features" in text
        or "feature extractio" in text
        or "featureextraction" in text
        or "特征提取" in text
    )

    # Check whether the user is NEGATING feature extraction
    # ("don't run feature extraction or training" / "不要做特征提取").
    # If so, feature extraction is OUT of scope — stop at acquisition.
    fe_negated = any(p.search(text) for p in (
        re.compile(r"\bdon'?t\s+(run\s+|do\s+|start\s+)?feature\s+extract"),
        re.compile(r"\bdo\s+not\s+(run\s+|do\s+|start\s+)?feature\s+extract"),
        re.compile(r"\bno\s+feature\s+extract"),
        re.compile(r"\bskip\s+feature\s+extract"),
        re.compile(r"不要(做|跑|进行|开始)?\s*feature\s*extraction"),
        re.compile(r"不要(做|跑|进行|开始)?\s*feature\s*extract"),
        re.compile(r"不(做|跑|进行|开始)\s*feature\s*extraction"),
        re.compile(r"不(做|跑|进行|开始)\s*feature\s*extract"),
        re.compile(r"不要(做|跑|进行|开始)?\s*特征提取"),
        re.compile(r"不(做|跑|进行|开始)\s*特征提取"),
    ))

    # "only data prep" / "just download" signals → stop at acquisition,
    # but ONLY when the user didn't ALSO ask for feature extraction
    # ("data prep AND feature extraction, stop" → feature_extraction wins).
    only_data_signal = any(tok in text for tok in (
        "just download", "only download", "data prep",
        "数据下载", "数据准备", "数据整理", "只下载", "下载和整理",
        "只完成数据检索", "只做数据", "只获取",
    ))
    if fe_negated or (only_data_signal and not fe_mentioned_positive):
        return "acquisition"

    # User explicitly wants feature extraction done.
    if fe_mentioned_positive:
        return "feature_extraction"

    # Plan-2026-05-14 stage3 P0-3: previously this returned
    # "feature_extraction" as a catch-all whenever "don't train" appeared.
    # That extrapolated *typical pipeline shape* into *user intent* —
    # session_64561aa7962b burnt 9 hours on PANDA MIL the user never
    # asked for, and this default was the equivalent bug one stage
    # earlier. Now we return "" so the catch-all responsibility falls
    # to the LLM picker (which has full prompt context), and the heuristic
    # only fires when it has a positive signal of its own.
    return ""


def _heuristic_skill_candidate(objective: ResearchObjective) -> str:
    """Plan T4: deterministic skill routing fallback for clearly-shaped tasks.

    Used only when the LLM router returns ``none``/``parse_error``/unknown
    skill — keeps obvious patch-classification or MIL questions from falling
    through to free mode (session_a70dd3a564c1: a "patch-level MSI classifier"
    objective ended up with selected_skill="" because the LLM returned
    parse_error and the existing path quietly accepted free mode).

    Plan-2026-05-14 stage3 P1-7: now derives the skill from the shared
    ``TASK_KEYWORD_RULES`` table (consumed by ``_regex_task_type`` too).
    Pre-fix this scanner and ``_regex_task_type`` had different priority
    orders and slightly different keyword sets, so a "survival +
    slide-level MIL" prompt resolved to different skills/types in each.
    The table's order (MIL > survival > segmentation > FE > patch) is
    the single source of priority truth.

    Returns "" when the task shape is genuinely ambiguous so we don't force
    an unrelated skill on a generic prompt.
    """
    text = " ".join([
        objective.question or "",
        objective.preferred_skill or "",
        objective.dataset_hint or "",
    ])
    for skill_name, _coarse_task, patterns in TASK_KEYWORD_RULES:
        if any(p.search(text) for p in patterns):
            return skill_name
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
    dataset from the question and emits the inferred value on the returned
    dict as ``dataset_hint_inferred`` so the director can mirror it onto
    state.

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
    policy = network_policy or NetworkPolicy()
    network_status = NetworkStatus(policy=policy)

    # 1. Dataset hint extraction (cheap regex+semantic, no LLM needed for
    #    the common case). Plan-2026-05-14 stage3 P1-1: factored into
    #    ``_phase_dataset_extraction`` so ground_objective stays a
    #    coordinator.
    effective_dataset_hint, _task_from_q, _phase1 = _phase_dataset_extraction(
        objective, llm_parser,
    )
    grounding.update(_phase1)

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
    enriched_profile, task_profile_sources = _resolve_task_profile(
        objective.question,
        dataset_hint=effective_dataset_hint,
        selected_skill="",
        enrichment=task_profile_enrichment,
        allow_shape_override=not bool((objective.preferred_skill or "").strip()),
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

    # 3. Skill selection — extracted into ``_phase_skill_selection`` for P1-1.
    available = _load_available_skills()
    _phase3, llm_stop_after_skill, available_names = _phase_skill_selection(
        objective,
        available=available,
        heuristic_profile=heuristic_profile,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_config=llm_config,
    )
    grounding.update(_phase3)

    # 2026-05-10 stop-after refactor: the LLM picker may set this field;
    # the heuristic provides a safety net for two cases:
    #   1. LLM parse_error — we still want to honor "don't train" intent.
    #   2. LLM forgot to set the field even though the user said "stop".
    # Order: LLM > heuristic. We never override an explicit LLM "" with a
    # heuristic value, since the LLM may have decided no stop is intended.
    heuristic_stop_after = _heuristic_stop_after_skill(objective.question or "")
    final_stop_after = (llm_stop_after_skill or heuristic_stop_after).strip()
    # Plan-2026-05-14 stage3 P0-2: validate stop_after_skill against the
    # registry. The LLM may emit "data_preparation", "mil",
    # "feature_extration" (typo) or any other freeform string — without
    # this check those flow unchecked into plan-truncation downstream and
    # the prompt-engineered safety net silently no-ops.
    _valid_stop_boundaries = {"acquisition", "feature_extraction", *available_names}
    if final_stop_after and final_stop_after not in _valid_stop_boundaries:
        logger.warning(
            "Grounding: ignoring unknown stop_after_skill=%r "
            "(valid: %s)", final_stop_after, sorted(_valid_stop_boundaries),
        )
        final_stop_after = ""
    if final_stop_after:
        grounding["stop_after_skill"] = final_stop_after

    # 4 + 5. Final task_profile with selected_skill applied, plus coarse
    #    task_type — extracted into ``_phase_finalize_profile`` for P1-1.
    selected_skill = (
        grounding.get("selected_skill", "") or objective.preferred_skill
    )
    profile, organ, task_type, _phase45 = _phase_finalize_profile(
        objective,
        effective_dataset_hint=effective_dataset_hint,
        task_profile_enrichment=task_profile_enrichment,
        selected_skill=selected_skill,
        selected_skill_source=str(grounding.get("selected_skill_source") or ""),
        task_from_question=_task_from_q,
        existing_sources=grounding.get("task_profile_sources"),
    )
    grounding.update(_phase45)

    # 6. Literature retrieval — receives organ/task filters now (T6) + policy (T8).
    grounding.update(
        _retrieve_literature(
            objective, literature_store,
            online_clients=online_clients or [],
            organ=organ, task_type=task_type,
            dataset_hint=effective_dataset_hint,
            task_profile=profile,
            network_policy=policy,
            paper_cache=paper_cache,
            literature_service=literature_service,
            llm_config=llm_config,
            llm_query_parser=task_profile_llm_parser,
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

    # P1 fix (2026-05-01): when objective.dataset_hint can't be extracted
    # from the user's question (e.g. "训练一个Gleason分级模型" — no
    # explicit dataset name), fall back to the task_profile's inferred
    # dataset_keywords / prediction_target before reporting
    # ``no_dataset_hint``. Pre-fix, the new fulltext+LLM SOTA path never
    # got a chance to run on prompts like this even though task_profile
    # had ``dataset_keywords=["PANDA","prostate","gleason","ISUP"]``
    # (sessions 4cbb1f7922ac, 6a2fba1d1789).
    sota_dataset = effective_dataset_hint
    sota_dataset_source = (
        "explicit" if (objective.dataset_hint or "").strip()
        else (
            "inferred_from_question" if effective_dataset_hint else ""
        )
    )
    if not sota_dataset:
        keywords = list(getattr(profile, "dataset_keywords", []) or [])
        if keywords:
            sota_dataset = keywords[0]
            sota_dataset_source = "task_profile_keywords"
        elif getattr(profile, "prediction_target", "") or "":
            sota_dataset = profile.prediction_target
            sota_dataset_source = "task_profile_prediction_target"

    if effective_sota_lookup is None:
        grounding["sota_lookup_status"] = "disabled"
        network_status.record(
            "sota", NetworkLegStatus(leg="sota", state="disabled"),
        )
    elif not sota_dataset:
        grounding["sota_lookup_status"] = "no_dataset_hint"
        network_status.record(
            "sota", NetworkLegStatus(leg="sota", state="not_invoked"),
        )
    else:
        if sota_dataset_source:
            grounding["sota_dataset_source"] = sota_dataset_source
        if sota_dataset != effective_dataset_hint:
            grounding["sota_dataset_used"] = sota_dataset
        lookup_task_type = task_type or "classification"
        try:
            target = effective_sota_lookup.lookup(
                dataset=sota_dataset,
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


def _phase_skill_selection(
    objective: ResearchObjective,
    *,
    available: list[dict],
    heuristic_profile,
    llm_model: str,
    llm_api_key: str,
    llm_base_url: str,
    llm_config,
) -> tuple[dict[str, Any], str, list[str]]:
    """Phase-3 of ``ground_objective``: pick selected_skill via the
    preferred → LLM → heuristic fallback chain.

    Plan-2026-05-14 stage3 P1-1: factored from the main body so the
    ~110-line selection block has a single named entry point instead of
    being inline. Returns ``(partial_grounding_dict, llm_stop_after_skill,
    available_names)`` — caller merges ``partial`` into the running
    grounding result and consumes the raw LLM stop_after value during
    stop-after resolution.
    """
    available_names = [s["name"] for s in available]
    partial: dict[str, Any] = {}
    llm_stop_after_skill = ""
    preferred = (objective.preferred_skill or "").strip()

    if preferred:
        # Plan-2026-04-29 grounding-routing-repair Task 4: validate
        # explicit preferred_skill against the registry. A typo like
        # ``mil_classfication`` must NOT pass through unchallenged.
        if preferred in available_names:
            logger.info("Grounding: using preferred skill %r", preferred)
            partial["selected_skill"] = preferred
            partial["selected_skill_source"] = "user"
            partial["route"] = "skill"
            partial["reason"] = "user-specified"
        else:
            candidate, fallback_source = _resolve_skill_fallback(
                objective, available_names, profile=heuristic_profile,
            )
            if candidate:
                logger.warning(
                    "Grounding: unknown preferred_skill %r, using %s → %r",
                    preferred, fallback_source, candidate,
                )
                partial["selected_skill"] = candidate
                partial["selected_skill_source"] = fallback_source
                partial["route"] = "skill"
                partial["reason"] = (
                    f"unknown_preferred_skill:{preferred}; {fallback_source}"
                )
            else:
                logger.warning(
                    "Grounding: unknown preferred_skill %r, falling "
                    "through to free mode", preferred,
                )
                partial["reason"] = f"unknown_preferred_skill:{preferred}"
        return partial, llm_stop_after_skill, available_names

    if not available:
        return partial, llm_stop_after_skill, available_names

    try:
        result = _llm_select_skill(
            objective, available,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_config=llm_config,
            profile=heuristic_profile,
        )
        selected = str(result.get("selected_skill", "none") or "none").strip()
        reason = result.get("reason", "")
        # 2026-05-10 stop-after refactor: capture LLM stop_after_skill;
        # merged with the heuristic safety net by the caller.
        llm_stop_after_skill = str(
            result.get("stop_after_skill", "") or ""
        ).strip().lower()
        selected_is_none = selected.lower() in {"", "none", "null"}

        if not selected_is_none and selected in available_names:
            logger.info("Grounding: LLM selected skill %r — %s", selected, reason)
            partial["selected_skill"] = selected
            partial["selected_skill_source"] = "llm"
            partial["route"] = "skill"
            partial["reason"] = reason
            return partial, llm_stop_after_skill, available_names

        if not selected_is_none and selected not in available_names:
            logger.warning(
                "LLM selected unknown skill %r, trying preferred_skill "
                "+ heuristic fallback", selected,
            )
        else:
            logger.info(
                "Grounding: LLM returned no skill (%s), trying "
                "preferred_skill + heuristic", reason,
            )
        candidate, fallback_source = _resolve_skill_fallback(
            objective, available_names, profile=heuristic_profile,
        )
        if candidate:
            logger.info(
                "Grounding: %s selected skill %r", fallback_source, candidate,
            )
            partial["selected_skill"] = candidate
            partial["selected_skill_source"] = fallback_source
            partial["route"] = "skill"
            partial["reason"] = (
                f"{fallback_source}: llm_returned={selected!r}, "
                f"reason={reason!r}"
            )
        else:
            partial["reason"] = reason
    except Exception as e:
        logger.warning(
            "LLM skill selection failed: %s, trying preferred_skill "
            "+ heuristic fallback", e,
        )
        candidate, fallback_source = _resolve_skill_fallback(
            objective, available_names, profile=heuristic_profile,
        )
        if candidate:
            logger.info(
                "Grounding: %s selected skill %r after LLM error",
                fallback_source, candidate,
            )
            partial["selected_skill"] = candidate
            partial["selected_skill_source"] = fallback_source
            partial["route"] = "skill"
            partial["reason"] = f"{fallback_source}: llm_error={type(e).__name__}"
        else:
            partial["reason"] = f"llm_error: {e}"

    return partial, llm_stop_after_skill, available_names


def _phase_finalize_profile(
    objective: ResearchObjective,
    *,
    effective_dataset_hint: str,
    task_profile_enrichment,
    selected_skill: str,
    task_from_question: str,
    existing_sources: dict[str, Any] | None,
    selected_skill_source: str = "",
) -> tuple[Any, str | None, str | None, dict[str, Any]]:
    """Phase-4/5 of ``ground_objective``: produce the final task profile,
    coarse task_type, and organ given the picked skill.

    Plan-2026-05-14 stage3 P1-1: factored from the main body so the
    skill-selection result feeds a single named helper instead of an
    interleaved inline block. Returns
    ``(profile, organ_or_none, coarse_task_type, partial_grounding_dict)``.
    """
    explicit_user_skill = selected_skill_source == "user"
    profile, final_sources = _resolve_task_profile(
        objective.question,
        dataset_hint=effective_dataset_hint,
        selected_skill=selected_skill,
        enrichment=task_profile_enrichment,
        allow_shape_override=not explicit_user_skill,
    )
    partial: dict[str, Any] = {"task_profile": profile.to_dict()}
    if final_sources:
        merged_sources = dict(existing_sources or {})
        merged_sources.update(final_sources)
        partial["task_profile_sources"] = merged_sources
    if (
        final_sources.get("task_shape") == "llm"
        and selected_skill_source != "user"
        and profile.preferred_skill
        and profile.preferred_skill != selected_skill
    ):
        partial["selected_skill"] = profile.preferred_skill
        partial["selected_skill_source"] = "llm_task_profile"
    if final_sources.get("dataset_hint_candidates"):
        partial["dataset_hint_candidates"] = list(
            final_sources["dataset_hint_candidates"]
        )
    organ = profile.organ or None
    task_type = _infer_task_type(
        objective,
        selected_skill=partial.get("selected_skill", selected_skill),
        task_hint=task_from_question,
    )
    return profile, organ, task_type, partial


def _phase_dataset_extraction(
    objective: ResearchObjective, llm_parser
) -> tuple[str, str, dict[str, Any]]:
    """Phase-1 of ``ground_objective``: extract dataset_hint + task_type
    signals from the question.

    Plan-2026-05-14 stage3 P1-1: extracted from the 460-line main
    ``ground_objective`` body so the orchestration is composable. Returns
    ``(effective_dataset_hint, task_from_question, partial_grounding_dict)``
    — caller merges ``partial`` into the running grounding result.
    """
    inferred_dataset, task_from_q = extract_dataset_and_task(
        objective.question,
        llm_parser=llm_parser,
        preferred_skill=objective.preferred_skill,
    )
    partial: dict[str, Any] = {}
    if (objective.dataset_hint or "").strip():
        effective_dataset_hint = objective.dataset_hint
        partial["dataset_hint_source"] = "explicit"
    elif inferred_dataset:
        partial["dataset_hint_inferred"] = inferred_dataset
        question_lower = objective.question.lower()
        dataset_lower = inferred_dataset.lower()
        if "/" in objective.question and dataset_lower in question_lower:
            partial["dataset_hint_source"] = "path_extract"
        elif dataset_lower in question_lower:
            partial["dataset_hint_source"] = "literal_regex"
        else:
            partial["dataset_hint_source"] = "semantic_inference"
        effective_dataset_hint = inferred_dataset
    else:
        partial["dataset_hint_source"] = ""
        effective_dataset_hint = ""
    if task_from_q:
        partial["task_type_inferred"] = task_from_q
    return effective_dataset_hint, task_from_q, partial


def _resolve_task_profile(
    question: str,
    *,
    dataset_hint: str,
    selected_skill: str,
    enrichment,
    allow_shape_override: bool,
):
    """Single entry point for ``infer_task_profile`` + enrichment merge.

    Plan-2026-05-14 stage3 P0-1: ``ground_objective`` historically called
    ``infer_task_profile`` and ``merge_task_profile_enrichment`` twice
    each — once for the picker hint (selected_skill=""), once for the
    final profile (with the picked skill). That left four lines of
    near-duplicate merge boilerplate where ``allow_task_shape_override``
    could silently diverge between passes. This helper centralises the
    pattern so the two passes share one resolver; the caller still
    decides ``selected_skill`` and ``allow_shape_override`` per phase.
    """
    base = infer_task_profile(
        question,
        selected_skill=selected_skill,
        dataset_hint=dataset_hint,
    )
    return merge_task_profile_enrichment(
        base,
        enrichment,
        allow_task_shape_override=allow_shape_override,
    )


def _build_inline_rerank_assist(literature_store, llm_config):
    """Build (reranker, alias_resolver) for the inline-fallback retriever path.

    The service-bound retriever already has these wired by
    ``runner._build_literature_service``. This helper rebuilds them when
    grounding takes the inline fallback (no LiteratureService present —
    typically resume paths or service construction failure). Returns
    ``(None, None)`` whenever any prerequisite is missing so the caller
    can fall through to the keyword-only behavior.
    """
    if literature_store is None or llm_config is None:
        return None, None
    try:
        from ..literature.alias_resolver import AliasResolver
        from ..literature.query_builder import builtin_dataset_alias_table
        from ..literature.relevance_reranker import RelevanceReranker
        from ..runtime.metric_parser import build_llm_text_caller

        llm_parser = build_llm_text_caller(llm_config)
        if llm_parser is None:
            return None, None
        lit_dir = getattr(literature_store, "_dir", None)
        alias_resolver = None
        if lit_dir is not None:
            alias_resolver = AliasResolver(
                cache_path=Path(lit_dir) / "seed_data" / "dataset_aliases.json",
                llm_parser=llm_parser,
                builtin_table=builtin_dataset_alias_table(),
            )
        return RelevanceReranker(llm_parser), alias_resolver
    except Exception as e:
        logger.warning("inline rerank assist build failed: %s", e)
        return None, None


def _build_literature_query(
    objective: ResearchObjective,
    task_profile,
    dataset_hint: str,
    organ: str | None,
    task_type: str | None,
) -> str:
    """Compose the search query string, threading task_profile signals in.

    Plan-2026-05-14 stage3 P1-8: extracted from ``_retrieve_literature`` so
    the 200-line orchestrator function only does coordination, not query
    composition.
    """
    from ..literature.query_builder import build_literature_search_query
    profile_task_type = getattr(task_profile, "task_type", "") if task_profile else ""
    prediction_target = (
        getattr(task_profile, "prediction_target", "") if task_profile else ""
    )
    required_label_keywords = (
        getattr(task_profile, "required_label_keywords", []) if task_profile else []
    )
    dataset_keywords = (
        getattr(task_profile, "dataset_keywords", []) if task_profile else []
    )
    return build_literature_search_query(
        objective.question,
        dataset_hint=dataset_hint,
        organ=organ,
        task_type=profile_task_type or task_type,
        prediction_target=prediction_target,
        required_label_keywords=required_label_keywords,
        dataset_keywords=dataset_keywords,
    )


_QUERY_NOISE_PHRASES = (
    "training a ai model",
    "training an ai model",
    "help me",
    "once you finished",
    "validate it on my own",
    "my own dataset",
)


def _build_literature_query_plan_prompt(
    objective: ResearchObjective,
    task_profile,
    *,
    dataset_hint: str,
    fallback_query: str,
) -> str:
    """Prompt the LLM for a structured literature-search query plan."""
    return f"""Generate a clean literature search query for computational pathology.
Return ONLY one JSON object. Do not include user instructions, local paths,
or workflow prose. Keep biomedical/task/dataset terms only.

The primary_query will be sent to online paper search engines. It should be
concise and specific enough to retrieve papers/baselines.

Schema:
{{
  "primary_query": "",
  "sota_query": "",
  "dataset_query": "",
  "must_include": [],
  "must_exclude": [],
  "task_level": "patch|slide|region|unknown",
  "modality": "patch_images|wsi|features|histology|unknown",
  "reason": ""
}}

User objective: {objective.question}
Dataset hint: {dataset_hint}
Task profile: {task_profile.to_dict() if task_profile is not None else {}}
Deterministic fallback query: {fallback_query}
"""


def _listify_strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _has_user_patch_intent(text: str) -> bool:
    return bool(
        re.search(
            r"\bpatch(?:es)?\b|\bpatch[- ]level\b|\btile(?:s)?\b",
            text or "",
            re.I,
        )
    )


def _required_query_anchors(task_profile) -> list[str]:
    anchors: list[str] = []
    if task_profile is None:
        return anchors
    for value in getattr(task_profile, "dataset_keywords", []) or []:
        token = str(value or "").strip()
        if token in {"TCGA-LUAD", "TCGA-LUSC", "TCGA-LUNG"}:
            anchors.append(token)
    for value in getattr(task_profile, "required_label_keywords", []) or []:
        token = str(value or "").strip()
        if token in {"LUAD", "LUSC", "NSCLC", "MSI", "MSI-H", "MSS"}:
            anchors.append(token)
    out: list[str] = []
    seen: set[str] = set()
    for token in anchors:
        key = token.lower()
        if key not in seen:
            out.append(token)
            seen.add(key)
    return out


def _validate_literature_query(
    query: str,
    *,
    objective: ResearchObjective,
    task_profile,
    llm_must_include: list[str],
) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    q = (query or "").strip()
    q_lower = q.lower()
    if not q:
        warnings.append("empty_primary_query")
    if re.search(r"(?:~|/)[^\s]+", q) or "/project/" in q_lower:
        warnings.append("contains_path")
    for phrase in _QUERY_NOISE_PHRASES:
        if phrase in q_lower:
            warnings.append(f"contains_user_instruction:{phrase}")

    profile_task = str(getattr(task_profile, "task_type", "") or "")
    if (
        profile_task != "patch_classification"
        and not _has_user_patch_intent(objective.question)
        and re.search(
            r"\bpatch(?:es)?\b|\bpatch[- ]level\b|\btile(?:s)?\b",
            q_lower,
        )
    ):
        warnings.append("patch_terms_without_patch_intent")

    for anchor in _required_query_anchors(task_profile):
        if anchor.lower() not in q_lower:
            warnings.append(f"missing_anchor:{anchor}")
    for anchor in llm_must_include:
        if anchor.lower() not in q_lower:
            warnings.append(f"missing_llm_must_include:{anchor}")

    hard_prefixes = (
        "empty_primary_query",
        "contains_path",
        "contains_user_instruction:",
        "patch_terms_without_patch_intent",
        "missing_anchor:TCGA-LUAD",
        "missing_anchor:TCGA-LUSC",
    )
    ok = not any(
        warn == prefix or warn.startswith(prefix)
        for warn in warnings
        for prefix in hard_prefixes
    )
    return ok, warnings


def _plan_literature_query(
    objective: ResearchObjective,
    task_profile,
    *,
    dataset_hint: str,
    fallback_query: str,
    llm_parser=None,
) -> tuple[str, dict[str, Any]]:
    """Return the search query plus an auditable query-plan payload.

    LLM output is useful for removing raw user prose from search strings, but
    it must pass deterministic checks before it can replace the fallback.
    """
    if llm_parser is None:
        return fallback_query, {
            "status": "fallback",
            "reason": "llm_unavailable",
            "fallback_query": fallback_query,
            "validation_warnings": [],
        }
    prompt = _build_literature_query_plan_prompt(
        objective, task_profile, dataset_hint=dataset_hint,
        fallback_query=fallback_query,
    )
    try:
        raw = llm_parser(prompt)
    except Exception as e:
        return fallback_query, {
            "status": "fallback",
            "reason": f"llm_error:{type(e).__name__}",
            "fallback_query": fallback_query,
            "validation_warnings": [],
        }
    data = _extract_first_json_object(str(raw or ""))
    if not isinstance(data, dict):
        return fallback_query, {
            "status": "fallback",
            "reason": "llm_parse_error",
            "fallback_query": fallback_query,
            "validation_warnings": ["llm_parse_error"],
        }

    primary_query = str(data.get("primary_query") or "").strip()
    must_include = _listify_strings(data.get("must_include"))
    ok, warnings = _validate_literature_query(
        primary_query,
        objective=objective,
        task_profile=task_profile,
        llm_must_include=must_include,
    )
    plan = {
        "status": "llm" if ok else "fallback",
        "primary_query": primary_query,
        "sota_query": str(data.get("sota_query") or "").strip(),
        "dataset_query": str(data.get("dataset_query") or "").strip(),
        "must_include": must_include,
        "must_exclude": _listify_strings(data.get("must_exclude")),
        "task_level": str(data.get("task_level") or "").strip(),
        "modality": str(data.get("modality") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
        "fallback_query": fallback_query,
        "validation_warnings": warnings,
    }
    if ok:
        return primary_query, plan
    plan["reason"] = plan["reason"] or "llm_query_failed_validation"
    return fallback_query, plan


def _resolve_paper_retriever(
    literature_store,
    literature_service,
    llm_config,
    online_clients,
    network_policy,
    paper_cache,
):
    """Pick the LiteratureRetriever for this grounding pass.

    Order: service-bound retriever > freshly-built inline retriever >
    ``None`` (no store available — caller emits ``disabled``). When the
    inline branch fires, the rerank/alias assist is rebuilt from
    ``llm_config`` so LLM relevance filtering survives resume paths
    where ``literature_service`` is unavailable.
    """
    if literature_service is not None:
        service_retriever = getattr(literature_service, "_literature", None)
        if service_retriever is not None:
            return service_retriever
    if literature_store is None:
        return None
    from ..literature.retriever import LiteratureRetriever
    inline_reranker, inline_alias = _build_inline_rerank_assist(
        literature_store, llm_config,
    )
    if inline_alias is not None and getattr(
        literature_store, "_alias_resolver", None,
    ) is None:
        literature_store._alias_resolver = inline_alias
    return LiteratureRetriever(
        literature_store,
        api_clients=online_clients or [],
        policy=network_policy,
        paper_cache=paper_cache,
        reranker=inline_reranker,
        alias_resolver=inline_alias,
    )


def _fetch_papers_and_baselines(
    retriever,
    objective: ResearchObjective,
    literature_query: str,
    *,
    organ,
    task_type,
    dataset_hint: str,
    prediction_target: str,
    top_k: int = 5,
):
    """Retrieve papers, then baselines filtered by reranked paper_ids.

    Plan-2026-05-14 stage3 P1-8: returns a ``(papers, baselines)`` tuple
    so the caller controls how to project them into the result dict.

    ``top_k`` is now caller-controlled (was hardcoded 5). The caller
    threads ``config.literature_online_max_results`` through so the
    ``PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS`` env var actually
    takes effect.
    """
    papers = retriever.retrieve(
        query=literature_query,
        organ=organ,
        task_type=task_type,
        top_k=top_k,
    )
    effective_dataset = (dataset_hint or "").strip()
    # Constrain baseline selection to papers that survived rerank so the
    # brief's baselines never come from a paper the reranker dropped as
    # off-topic. When papers is empty we let the call through unfiltered.
    retained_paper_ids = {p.paper_id for p in papers if p.paper_id} or None
    try:
        baselines = retriever.get_baselines_for_task(
            query=literature_query,
            dataset=effective_dataset if effective_dataset else None,
            task_type=task_type,
            top_k=top_k,
            organ=organ,
            prediction_target=prediction_target,
            metric_name=objective.success_metric,
            paper_filter=retained_paper_ids,
        )
    except TypeError:
        # Back-compat for service/retriever test doubles using the
        # pre-benchmark-store signature (no kwargs beyond the base set).
        baselines = retriever.get_baselines_for_task(
            query=literature_query,
            dataset=effective_dataset if effective_dataset else None,
            task_type=task_type,
            top_k=top_k,
        )
    return papers, baselines


def _summarize_online_status(retriever) -> dict[str, Any]:
    """Translate ``retriever.last_online_status`` into the grounding
    dict's online_literature_* keys.

    Plan-2026-05-14 stage3 P1-8: extracted from ``_retrieve_literature``
    so the status-state-machine can be unit-tested without spinning up
    a full retriever pipeline.
    """
    online_stat = getattr(retriever, "last_online_status", {}) or {}
    provider_records = list(online_stat.get("providers", []) or [])
    out: dict[str, Any] = {
        "local_paper_count": int(online_stat.get("local_count", 0)),
        "online_literature_providers": provider_records,
    }
    if online_stat.get("query"):
        out["online_literature_query"] = online_stat["query"]

    if not online_stat.get("enabled", False):
        out["online_literature_status"] = "disabled"
        return out
    if not provider_records:
        out["online_literature_status"] = "not_invoked"
        return out

    errors = [p for p in provider_records if p.get("error")]
    merged = sum(int(p.get("merged", 0) or 0) for p in provider_records)
    if errors and merged == 0:
        out["online_literature_status"] = "error"
        out["online_literature_error"] = errors[0]["error"]
        out["online_literature_provider"] = errors[0]["provider"]
    elif merged == 0:
        out["online_literature_status"] = "no_results"
        out["online_literature_provider"] = provider_records[0]["provider"]
    else:
        out["online_literature_status"] = "ok"
        out["online_literature_count"] = merged
        # Pick the provider that contributed the most papers as the
        # canonical attribution.
        top = max(provider_records, key=lambda p: int(p.get("merged", 0) or 0))
        out["online_literature_provider"] = top["provider"]
    return out


def _retrieve_literature(
    objective: ResearchObjective,
    literature_store,
    online_clients: list | None = None,
    *,
    organ: str | None = None,
    task_type: str | None = None,
    dataset_hint: str = "",
    task_profile=None,  # TaskProfile | None
    network_policy=None,  # NetworkPolicy | None
    paper_cache=None,  # PaperCache | None — Phase 2 / Task 6
    literature_service=None,  # LiteratureService | None — Phase 4b
    llm_config: PathScientistConfig | None = None,
    llm_query_parser=None,
) -> dict[str, Any]:
    """Retrieve papers and baselines from literature store + optional online fill.

    Plan-2026-05-14 stage3 P1-8: this function is now a thin coordinator.
    The heavy lifting lives in four helpers:
        ``_build_literature_query``    — query composition
        ``_resolve_paper_retriever``   — service-bound vs inline retriever
        ``_fetch_papers_and_baselines``— retrieve + paper-filtered baselines
        ``_summarize_online_status``   — provider records → status fields

    The returned dict shape is preserved verbatim so callers in
    ``ground_objective`` and the persistence layer don't need updates.
    """
    result: dict[str, Any] = {
        "papers": [], "baselines": [], "citations": [],
        "local_paper_count": 0,
        "baseline_status": "not_invoked",
        "online_literature_status": "disabled" if not online_clients else "not_invoked",
        "online_literature_providers": [],
    }

    fallback_query = _build_literature_query(
        objective, task_profile, dataset_hint, organ, task_type,
    )
    active_query_parser = (
        llm_query_parser
        if (literature_store is not None or literature_service is not None)
        else None
    )
    literature_query, query_plan = _plan_literature_query(
        objective,
        task_profile,
        dataset_hint=dataset_hint,
        fallback_query=fallback_query,
        llm_parser=active_query_parser,
    )
    result["literature_search_query"] = literature_query
    result["deterministic_literature_search_query"] = fallback_query
    result["literature_query_plan"] = query_plan

    retriever = _resolve_paper_retriever(
        literature_store, literature_service, llm_config,
        online_clients, network_policy, paper_cache,
    )
    if retriever is None:
        result["online_literature_status"] = "disabled"
        return result

    prediction_target = (
        getattr(task_profile, "prediction_target", "") if task_profile else ""
    )
    # Wire ``PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS`` through. Default
    # 5 preserves the historical hardcoded value when llm_config is absent
    # (tests, resume paths).
    top_k = int(getattr(llm_config, "literature_online_max_results", 0) or 5)
    try:
        papers, baselines = _fetch_papers_and_baselines(
            retriever, objective, literature_query,
            organ=organ, task_type=task_type,
            dataset_hint=dataset_hint,
            prediction_target=prediction_target,
            top_k=top_k,
        )
        result["papers"] = [
            {"paper_id": p.paper_id, "title": p.title, "year": p.year,
             "source": p.source, "url": p.url}
            for p in papers
        ]
        result["baselines"] = [b.to_dict() for b in baselines]
        result["citations"] = [
            {"paper_id": p.paper_id, "title": p.title} for p in papers
        ]

        if baselines:
            result["baseline_status"] = "ok"
        elif papers:
            result["baseline_status"] = "no_matching_benchmark"
        else:
            result["baseline_status"] = "no_papers"

        result.update(_summarize_online_status(retriever))

        # Plan-2026-05-14 stage3 P2-4: hot-path logs use %-formatting so
        # arg interpolation skips when the level is suppressed (cheaper
        # at scale than rendering an f-string up-front).
        if baselines:
            best = baselines[0]
            logger.info(
                "Literature: found %d papers (local=%d, online_status=%s), "
                "best baseline: %s %s=%s on %s",
                len(papers), result["local_paper_count"],
                result["online_literature_status"],
                best.method, best.metric_name, best.metric_value, best.dataset,
            )
        else:
            logger.info(
                "Literature: found %d papers (local=%d, online_status=%s), "
                "no baselines extracted",
                len(papers), result["local_paper_count"],
                result["online_literature_status"],
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
        logger.warning("Literature retrieval failed: %s", e)
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
