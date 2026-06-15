"""Research session runner — wraps the code agent with orchestrator stage management."""
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

from ..config import PathScientistConfig
from ..literature.benchmark_extractor import BenchmarkExtractor
from ..literature.pwc_client import PapersWithCodeClient
from ..literature.sota_cache import SotaCache
from ..literature.sota_lookup import SotaLookup
from ..orchestrator.director import ResearchDirector
from ..orchestrator.external_contract import (
    normalize_external_test_contract,
    update_external_dataset,
)
from ..orchestrator.external_request import infer_external_request
from ..orchestrator.prompts import build_execution_brief
from ..orchestrator.review import run_review_stage
from ..orchestrator.state_bridge import persist_research_session_state
from ..orchestrator.summary import build_session_summary
from ..orchestrator.types import (
    MAX_IDLE_TURNS,
    MAX_NON_FINALIZED_TURNS,
    STAGE_ACQUISITION,
    STAGE_COMPLETED,
    STAGE_EXECUTION,
    STAGE_GROUNDING,
    STAGE_PRE_EXECUTION_READY,
    STAGE_SYNTHESIS,
    ResearchObjective,
    ResearchSessionState,
    RunRecord,
)
from ..orchestrator.ui_summary import build_ui_run_summary
from ..runtime.integrity import check_session_integrity
from ..runtime.session import DEFAULT_BASE_DIR

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[ResearchSessionState], None]


def _notify_progress(
    progress_callback: ProgressCallback | None,
    state: ResearchSessionState,
) -> None:
    """Best-effort UI progress hook; never let streaming break the runner."""
    if progress_callback is None:
        return
    try:
        progress_callback(state)
    except Exception as exc:
        logger.debug("PathScientist progress callback failed: %s", exc)


def _build_paper_registry(session):
    """Plan-2026-04-29 literature-acquisition Phase 5 / Task 4:
    session-scoped ``PaperRegistry`` persisted at
    ``persistence_root/paper_registry.json``. Loads existing entries on
    startup so multi-session ingestion is sticky.
    """
    try:
        persist_root = getattr(session, "persistence_root", None)
        if not persist_root or str(persist_root) in ("", "."):
            logger.warning(
                "PaperRegistry: session.persistence_root is unset (%r); "
                "skipping registry",
                persist_root,
            )
            return None
        from ..literature.paper_registry import PaperRegistry
        return PaperRegistry.load(Path(persist_root) / "paper_registry.json")
    except Exception as e:
        logger.warning("PaperRegistry construction failed: %s", e)
        return None


def _build_literature_service(
    *,
    literature_store,
    online_clients,
    sota_lookup,
    literature_retriever,
    paper_cache,
    network_policy,
    paper_registry=None,
    config=None,
):
    """Plan-2026-04-29 literature-acquisition Phase 4 / Task 6: build
    the unified LiteratureService that wraps:
    - LiteratureRetriever (paper-search + baselines, with PaperCache)
    - HybridLiteratureRetriever (RAG passages, already constructed)
    - SotaLookup (target metric)

    Returns ``None`` when ``literature_store`` is missing — without a
    store there's no useful paper-search facade. (Passages + SOTA could
    still work, but consumers can fall back to direct refs in that
    edge case.)
    """
    if literature_store is None:
        return None
    try:
        from ..literature.alias_resolver import AliasResolver
        from ..literature.query_builder import builtin_dataset_alias_table
        from ..literature.relevance_reranker import RelevanceReranker
        from ..literature.retriever import LiteratureRetriever
        from ..literature.service import LiteratureService
        from ..runtime.metric_parser import build_llm_text_caller

        llm_parser = build_llm_text_caller(config) if config is not None else None
        # Alias cache lives next to the literature corpus (global, not
        # session-scoped) so learned mappings survive across runs.
        alias_resolver = None
        reranker = None
        try:
            lit_dir = getattr(literature_store, "_dir", None)
            if lit_dir is not None:
                alias_resolver = AliasResolver(
                    cache_path=Path(lit_dir) / "seed_data" / "dataset_aliases.json",
                    llm_parser=llm_parser,
                    builtin_table=builtin_dataset_alias_table(),
                )
                # Reuse the store-level resolver for in-store query expansion
                # so local search benefits from LLM-learned synonyms too.
                literature_store._alias_resolver = alias_resolver
            reranker = RelevanceReranker(llm_parser)
        except Exception as e:
            logger.warning(
                "LiteratureService: alias/rerank wiring skipped (%s)", e,
            )

        # The service-bound LiteratureRetriever shares cache + policy
        # with grounding's _retrieve_literature path so cache hits land
        # in the same JSON file.
        paper_retriever = LiteratureRetriever(
            store=literature_store,
            api_clients=list(online_clients or []),
            policy=network_policy,
            paper_cache=paper_cache,
            reranker=reranker,
            alias_resolver=alias_resolver,
        )
        return LiteratureService(
            literature_retriever=paper_retriever,
            passage_retriever=literature_retriever,
            sota_lookup=sota_lookup,
            paper_registry=paper_registry,
            network_policy=network_policy,
        )
    except Exception as e:
        logger.warning("LiteratureService construction failed: %s", e)
        return None


def _build_paper_cache(session):
    """Construct a session-scoped PaperCache at ``persistence_root/paper_cache.json``.

    Plan-2026-04-29 literature-acquisition Phase 2 / Task 6: returns
    ``None`` when the session has no usable persistence_root (mirrors
    ``_build_sota_lookup`` behavior — never write at cwd).
    """
    try:
        persist_root = getattr(session, "persistence_root", None)
        if not persist_root or str(persist_root) in ("", "."):
            logger.warning(
                "PaperCache: session.persistence_root is unset (%r); "
                "skipping paper cache",
                persist_root,
            )
            return None
        from ..literature.paper_cache import PaperCache
        return PaperCache(Path(persist_root) / "paper_cache.json")
    except Exception as e:
        logger.warning("PaperCache construction failed: %s", e)
        return None


def _build_sota_lookup(session, config, literature_store) -> "SotaLookup | None":
    """Construct a SotaLookup rooted at the session's conversation-scoped
    persistence directory. Returns None if the runner can't wire one (e.g.
    missing persistence path) — grounding tolerates None.

    The cache path is built from ``session.persistence_root`` (a
    ``runtime.session.PathScientistSession``), NOT from ``config`` — the
    ``PathScientistConfig`` dataclass has no ``persistence_root`` field, so
    an earlier ``getattr(config, "persistence_root", ".")`` would silently
    fall back to the process cwd.
    """
    try:
        persist_root = getattr(session, "persistence_root", None)
        if not persist_root or str(persist_root) in ("", "."):
            logger.warning(
                "SotaLookup: session.persistence_root is unset (%r); "
                "refusing to build a cache at cwd",
                persist_root,
            )
            return None
        cache_path = Path(persist_root) / "sota_cache.json"
        offline = bool(getattr(config, "no_online_sota", False))
        pwc = None if offline else PapersWithCodeClient()
        online = None
        extractor = None
        fulltext_fetcher = None
        if not offline:
            try:
                # Plan-2026-04-29 literature-acquisition Phase 1 / Task 3:
                # share OpenAlex client per session so paper search and
                # SOTA benchmark extraction don't double-instantiate.
                from ..literature.online_clients import (
                    get_or_create_online_client,
                )
                online = get_or_create_online_client(
                    provider="openalex",
                    timeout=int(getattr(config, "literature_online_timeout", 15) or 15),
                    session_id=getattr(session, "session_id", "") or "",
                )
            except Exception as e:
                logger.warning("SotaLookup: openalex client init failed: %s", e)
            try:
                # Plan-2026-04-29 P0-3: was wired to ``build_llm_metric_parser``,
                # which has signature ``(text, primary_metric) -> dict`` —
                # incompatible with BenchmarkExtractor's ``(prompt) -> str``
                # contract. Result: every openalex+llm fallback raised
                # "_parser() missing 1 required positional argument:
                # 'primary_metric'" and the lookup collapsed to a clean
                # ``miss``. Use the generic text caller.
                from ..runtime.metric_parser import build_llm_text_caller
                extractor = BenchmarkExtractor(
                    llm_parser=build_llm_text_caller(config),
                )
            except Exception as e:
                logger.warning("SotaLookup: LLM extractor init failed: %s", e)
            try:
                # FT-T5: wire OA HTML full-text fetcher so SotaLookup can
                # extract benchmark numbers from tables + Results sections,
                # not just OpenAlex abstracts. Cache lives next to the
                # SotaCache under session.persistence_root so it survives
                # session restarts but stays scoped to this conversation.
                from ..literature.fulltext_cache import FulltextCache
                from ..literature.fulltext_fetcher import FulltextFetcher
                fulltext_fetcher = FulltextFetcher(
                    cache=FulltextCache(Path(persist_root) / "fulltext_cache"),
                    rate_limit_seconds=1.5,
                )
            except Exception as e:
                logger.warning(
                    "SotaLookup: FulltextFetcher init failed: %s", e,
                )
        return SotaLookup(
            store=literature_store,
            cache=SotaCache(cache_path),
            pwc_client=pwc,
            online_client=online,
            llm_extractor=extractor,
            offline=offline,
            refresh=bool(getattr(config, "refresh_sota", False)),
            fulltext_fetcher=fulltext_fetcher,
        )
    except Exception as e:
        logger.warning("SotaLookup construction failed: %s", e)
        return None


def _select_feature_extractor(
    *, config, task_profile, grounding, session,
):
    """Plan-2026-05-17: LLM-driven extractor selection grounded in
    grounding's papers/baselines/SOTA.

    Construction is best-effort — any failure (no LLM, no catalog,
    selector exception) silently falls back to the legacy env-var
    behavior so existing tests/CI paths keep working. Returns a
    ``ExtractorSelection`` (which has ``.name`` for the runtime registry
    key and ``.to_dict()`` for state persistence).
    """
    from ..domain.extractor_selector import (
        ExtractorSelection,
        FeatureExtractorSelector,
        load_catalog_from_skills,
    )
    from ..runtime.metric_parser import build_llm_text_caller

    env_override = os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR", "").strip()

    try:
        catalog = load_catalog_from_skills()
        llm_parser = build_llm_text_caller(config)
        cache_path = None
        persist_root = getattr(session, "persistence_root", None)
        if persist_root and str(persist_root) not in ("", "."):
            cache_path = Path(persist_root) / "extractor_choice_cache.json"
        selector = FeatureExtractorSelector(
            llm_parser=llm_parser,
            catalog=catalog,
            cache_path=cache_path,
        )
        selection = selector.select(
            task_profile=task_profile,
            papers=(grounding or {}).get("papers") or [],
            baselines=(grounding or {}).get("baselines") or [],
            sota_target=(grounding or {}).get("sota_target"),
            env_override=env_override,
        )
        logger.info(
            "FeatureExtractorSelector: picked %s (source=%s, confidence=%s) — %s",
            selection.canonical, selection.source,
            selection.confidence, selection.reason,
        )
        return selection
    except Exception as e:
        logger.warning(
            "FeatureExtractorSelector failed (%s); falling back to env/default.", e,
        )
        from .execution_plan import normalize_feature_extractor_name

        canonical = env_override or "Virchow2"
        return ExtractorSelection(
            name=normalize_feature_extractor_name(canonical),
            canonical=canonical,
            reason=f"selector unavailable: {type(e).__name__}",
            source="env" if env_override else "default",
            confidence="low",
        )


def _select_mil_model(
    *, config, task_profile, grounding, session,
):
    """Select the MIL aggregator from grounded literature with fallbacks."""
    from ..domain.mil_selector import (
        DEFAULT_MIL_MODEL,
        MILModelSelection,
        MILModelSelector,
    )
    from ..runtime.metric_parser import build_llm_text_caller

    env_override = os.environ.get("PATHSCIENTIST_MIL_MODEL", "").strip()
    try:
        llm_parser = build_llm_text_caller(config)
        cache_path = None
        persist_root = getattr(session, "persistence_root", None)
        if persist_root and str(persist_root) not in ("", "."):
            cache_path = Path(persist_root) / "mil_model_choice_cache.json"
        selector = MILModelSelector(
            llm_parser=llm_parser,
            cache_path=cache_path,
        )
        selection = selector.select(
            task_profile=task_profile,
            papers=(grounding or {}).get("papers") or [],
            baselines=(grounding or {}).get("baselines") or [],
            sota_target=(grounding or {}).get("sota_target"),
            env_override=env_override,
        )
        logger.info(
            "MILModelSelector: picked %s (source=%s, confidence=%s) - %s",
            selection.canonical,
            selection.source,
            selection.confidence,
            selection.reason,
        )
        return selection
    except Exception as e:
        logger.warning(
            "MILModelSelector failed (%s); falling back to env/default.", e,
        )
        from ..domain.mil_selector import (
            canonical_mil_model_name,
            normalize_mil_model_name,
        )

        name = normalize_mil_model_name(env_override or DEFAULT_MIL_MODEL)
        return MILModelSelection(
            name=name,
            canonical=canonical_mil_model_name(name),
            reason=f"selector unavailable: {type(e).__name__}",
            source="env" if env_override else "default",
            confidence="low",
        )


def _apply_external_request_inference(
    state,
    config,
    *,
    selected_skill: str = "",
    llm_caller=None,
):
    """Populate external_test config from LLM natural-language inference.

    Explicit API/env contracts win. The LLM decides semantic intent; this seam
    only applies the validated contract returned by ``external_request``.
    """
    grounding = getattr(state, "grounding", None)
    if not isinstance(grounding, dict):
        state.grounding = {}
        grounding = state.grounding

    explicit_contract = normalize_external_test_contract(
        getattr(config, "external_test_contract", {}) or {}
    )
    if explicit_contract:
        config.external_test_contract = dict(explicit_contract)
        grounding["external_test_request"] = {
            "source": "explicit_config",
            "requested": True,
            "enabled": bool(getattr(config, "external_test_enabled", False)),
            "contract": explicit_contract,
            "missing": [],
            "status": "explicit_config",
        }
        return None

    if (getattr(config, "skill_name", "") or "").strip() == "external_test":
        grounding["external_test_request"] = {
            "source": "explicit_config",
            "requested": True,
            "enabled": True,
            "contract": {},
            "missing": [],
            "status": "explicit_external_test_skill",
        }
        return None

    profile = (
        getattr(state, "task_profile", None)
        or grounding.get("task_profile")
        or {}
    )
    question = getattr(getattr(state, "objective", None), "question", "") or ""
    result = infer_external_request(
        question=question,
        selected_skill=selected_skill,
        task_profile=profile if isinstance(profile, dict) else {},
        data_mounts=getattr(config, "data_mounts", {}) or {},
        llm_caller=llm_caller,
        config=None if llm_caller is not None else config,
    )
    grounding["external_test_request"] = result.to_dict()
    if result.enabled:
        config.external_test_enabled = True
        config.external_test_contract = dict(result.contract)
    return result


def _prepare_data_readiness_and_execution_plan(
    state: ResearchSessionState,
    session,
    config,
) -> ResearchSessionState:
    """Plan-2026-04-30 data-readiness Task 6: assess data readiness from
    manifest + data_mounts + objective question, then build an execution
    plan. Mutates ``state.data_readiness`` and ``state.execution_plan``
    in place, plus mirrors them under ``state.grounding`` for brief access.
    """
    from pathlib import Path as _Path

    from ..dataset.manifests import load_manifest
    from ..dataset.readiness import assess_data_readiness
    from ..dataset.types import TaskProfile
    from .execution_plan import build_execution_plan, normalize_feature_extractor_name
    from ..domain.mil_selector import DEFAULT_MIL_MODEL

    profile_dict = state.task_profile or (state.grounding or {}).get("task_profile") or {}
    if not profile_dict and (
        getattr(config, "external_test_enabled", False)
        or getattr(config, "skill_name", "") == "external_test"
    ):
        profile_dict = {
            "task_type": "external_test",
            "asset_level": "slide",
            "input_modality": "features",
            "label_granularity": "slide",
            "preferred_skill": "external_test",
        }
        state.task_profile = dict(profile_dict)
        state.grounding["selected_skill"] = "external_test"
        state.grounding["task_profile"] = dict(profile_dict)
    if not profile_dict:
        return state

    prepared_contract: dict[str, str] = {}
    manifest_mounts: dict[str, str] = {}
    manifest_raw_root = ""
    if state.dataset_manifest_path:
        try:
            manifest = load_manifest(_Path(state.dataset_manifest_path))
            prepared_contract = dict(manifest.prepared_contract or {})
            manifest_mounts = dict(manifest.data_mounts or {})
            manifest_raw_root = manifest.raw_root or ""
        except Exception as exc:
            logger.info("readiness: manifest load skipped (%s)", exc)
            state.grounding["data_readiness_error"] = str(exc)

    profile = TaskProfile.from_dict(profile_dict)
    # Plan-2026-05-17: select the feature extractor before data readiness so
    # existing feature caches are checked against the same model the execution
    # contract will freeze.
    extractor_selection = _select_feature_extractor(
        config=config,
        task_profile=profile.to_dict(),
        grounding=state.grounding or {},
        session=session,
    )
    extractor_name = extractor_selection.name
    state.grounding["selected_extractor"] = extractor_selection.to_dict()

    workspace_root = _Path(session.workspace_dir)
    data_mounts: dict[str, str] = {}
    data_mounts.update(manifest_mounts)
    data_mounts.update(getattr(config, "data_mounts", {}) or {})

    readiness = assess_data_readiness(
        profile,
        prepared_contract=prepared_contract,
        data_mounts=data_mounts,
        question=state.objective.question,
        generated_contract_root=workspace_root / ".dataset" / "readiness",
        preferred_feature_extractor=extractor_name,
    )
    selected_skill = (state.grounding or {}).get("selected_skill", "") or profile.preferred_skill
    mil_selection = None
    if selected_skill == "mil_classification" or profile.task_type == "mil_classification":
        mil_selection = _select_mil_model(
            config=config,
            task_profile=profile.to_dict(),
            grounding=state.grounding or {},
            session=session,
        )
        state.grounding["selected_mil_model"] = mil_selection.to_dict()
    mil_model_name = mil_selection.name if mil_selection is not None else DEFAULT_MIL_MODEL
    state.grounding["model_selection_contract"] = {
        "frozen": True,
        "feature_extractor": extractor_selection.to_dict(),
        "mil_model": (
            mil_selection.to_dict()
            if mil_selection is not None
            else {}
        ),
        "policy": (
            "Use the selected foundation model and MIL aggregator for all "
            "iterations. Tune hyperparameters only; change architecture only "
            "when the user explicitly asks for architecture exploration."
        ),
    }
    # 2026-05-10 stop-after refactor: forward the user's stop boundary so
    # the plan truncates downstream training when "don't train" was set.
    stop_after_skill = (state.grounding or {}).get("stop_after_skill", "") or ""
    # DC-3 (2026-05-10): drop features alongside WSIs (under the
    # dataset-centric folder) when readiness identifies a recognizable
    # ``<dataset_root>/WSIs/`` layout. Falls back to workspace-local
    # otherwise. Pre-fix this was hard-coded to
    # ``<workspace>/.dataset/generated_features``.
    #
    # Prefer ``wsi_dir_host`` over ``wsi_dir``: when data is mounted,
    # ``wsi_dir`` is the in-sandbox path (``/data/WSIs``) which has
    # no relationship to the host filesystem; the host path lives on
    # the parallel ``_host`` field.
    wsi_dir_host = (
        getattr(readiness, "wsi_dir_host", "") or ""
    ) or (getattr(readiness, "wsi_dir", "") or "")
    feature_output_root = _resolve_features_data_output_dir(
        workspace_root=workspace_root,
        wsi_dir=wsi_dir_host,
        raw_root=manifest_raw_root,
    )
    _apply_external_request_inference(
        state,
        config,
        selected_skill=selected_skill,
    )
    plan = build_execution_plan(
        profile=profile,
        selected_skill=selected_skill,
        readiness=readiness,
        allow_acquisition=bool(getattr(config, "auto_acquire_data", False)),
        acquisition_status=state.acquisition_status,
        data_output_dir=str(feature_output_root),
        generated_features_dir=str(
            feature_output_root / "pt_files" / extractor_name
        ),
        extractor_name=extractor_name,
        mil_model_name=mil_model_name,
        stop_after_skill=stop_after_skill,
        external_test_enabled=bool(getattr(config, "external_test_enabled", False)),
        external_test_contract=dict(getattr(config, "external_test_contract", {}) or {}),
    )

    state.data_readiness = readiness.to_dict()
    state.execution_plan = plan.to_dict()
    state.grounding["data_readiness"] = state.data_readiness
    state.grounding["execution_plan"] = state.execution_plan

    # 2026-05-10 P0-2 fix: mirror the orchestrator's chosen stable
    # feature output path onto the config so RunExperimentTool can
    # honor it when the agent runs a feature_extraction script.
    # Without this, run_experiment falls back to a per-run dir that
    # gets purged when the session ends — losing 9 hours of
    # extracted features (session_64561aa7962b).
    _sync_planned_feature_extraction_env_from_current_step(state, config)

    train_step = next(
        (s for s in plan.steps if s.id == "train_downstream"),
        None,
    )
    if train_step is not None:
        config.planned_mil_model = train_step.inputs.get("mil_model_name") or ""
    elif hasattr(config, "planned_mil_model"):
        config.planned_mil_model = ""

    return state


def _current_execution_skill(state: ResearchSessionState) -> str:
    """Return the skill of the current execution-plan step, or empty.

    Local mirror of ``orchestrator.prompts._current_execution_skill`` to
    avoid pulling the brief module into the runner's import graph and to
    keep this hot-loop check cheap.
    """
    plan = state.execution_plan or (state.grounding or {}).get("execution_plan") or {}
    steps = plan.get("steps") or []
    current = int(plan.get("current_step", 0) or 0)
    if 0 <= current < len(steps):
        step = steps[current]
        if isinstance(step, dict):
            return str(step.get("skill") or "")
    return ""


def _current_execution_step(state) -> dict:
    plan = getattr(state, "execution_plan", None) or (getattr(state, "grounding", {}) or {}).get("execution_plan") or {}
    steps = plan.get("steps") or []
    current = int(plan.get("current_step", 0) or 0)
    if 0 <= current < len(steps) and isinstance(steps[current], dict):
        return steps[current]
    return {}


def _sync_planned_feature_extraction_env_from_current_step(state, config) -> None:
    """Mirror the current feature_extraction step into run_experiment env config."""
    step = _current_execution_step(state)
    if step.get("skill") != "feature_extraction":
        for attr in (
            "planned_data_output_dir",
            "planned_feature_wsi_dir",
            "planned_feature_extractor",
        ):
            if hasattr(config, attr):
                setattr(config, attr, "")
        return
    inputs = step.get("inputs") or {}
    config.planned_data_output_dir = inputs.get("data_output_dir") or ""
    config.planned_feature_wsi_dir = inputs.get("wsi_dir") or ""
    config.planned_feature_extractor = inputs.get("extractor_name") or ""


def _advance_execution_plan_after_iteration(
    state: ResearchSessionState,
    *,
    workspace_root: Path,
) -> bool:
    """Plan-2026-04-30 data-readiness Task 8: bump current_step from 0
    (feature_extraction setup) to 1 (downstream training) when the
    expected ``features_dir`` has produced ``.pt`` files.

    Setup is not an iteration: callers must NOT increment
    ``iteration_index`` or append a training ``RunRecord`` for the
    feature_extraction step.

    Returns True iff the plan advanced.
    """
    plan = state.execution_plan or {}
    steps = list(plan.get("steps") or [])
    current = int(plan.get("current_step", 0) or 0)
    if current >= len(steps):
        return False
    step = steps[current]
    if not isinstance(step, dict) or step.get("skill") != "feature_extraction":
        return False

    from ..dataset.readiness import find_generated_features_dir

    expected = (step.get("outputs") or {}).get("features_dir", "")
    features_dir = find_generated_features_dir(workspace_root, expected_dir=expected)
    if features_dir is None:
        return False

    actual_features_dir = str(features_dir)
    step_id = str(step.get("id") or "")
    step.setdefault("outputs", {})["features_dir"] = actual_features_dir
    if current + 1 < len(steps):
        next_step = steps[current + 1]
        if isinstance(next_step, dict):
            next_inputs = next_step.setdefault("inputs", {})
            if step_id == "extract_external_features":
                next_inputs.update(
                    update_external_dataset(
                        next_inputs,
                        {"features_dir": actual_features_dir},
                    )
                )
            else:
                next_inputs["features_dir"] = actual_features_dir

    plan["current_step"] = current + 1
    plan["steps"] = steps
    state.execution_plan = plan
    if step_id == "extract_external_features":
        request = state.grounding.get("external_test_request")
        if isinstance(request, dict):
            contract = dict(request.get("contract") or {})
            contract = update_external_dataset(
                contract,
                {"features_dir": actual_features_dir},
            )
            request["contract"] = contract
            request["missing"] = [
                item for item in (request.get("missing") or [])
                if item not in {"external_features_dir", "external_data_path"}
            ]
            state.grounding["external_test_request"] = request
    else:
        state.data_readiness = {
            **(state.data_readiness or {}),
            "status": "features_ready",
            "features_dir": actual_features_dir,
            "features_dir_host": actual_features_dir,
            "missing": [
                item for item in (state.data_readiness or {}).get("missing", [])
                if item != "features_dir"
            ],
        }
    state.grounding["execution_plan"] = state.execution_plan
    if step_id != "extract_external_features":
        state.grounding["data_readiness"] = state.data_readiness
    return True


def _advance_execution_plan_after_metric_step(
    state: ResearchSessionState,
    *,
    last_experiment: dict | None = None,
) -> bool:
    """Advance model-producing/external-test plan steps after ratchet finalizes.

    Training iterations normally stay on ``train_downstream`` until the
    iteration budget is exhausted. If an ``external_test`` step is queued next,
    move to it once the training budget has produced its final model. When the
    external step itself finalizes, mark the session ready for synthesis.
    """
    plan = state.execution_plan or {}
    steps = list(plan.get("steps") or [])
    current = int(plan.get("current_step", 0) or 0)
    if current >= len(steps):
        return False
    step = steps[current]
    if not isinstance(step, dict):
        return False

    skill = str(step.get("skill") or "")
    next_index = current + 1
    next_step = steps[next_index] if next_index < len(steps) else None
    next_is_external = (
        isinstance(next_step, dict)
        and str(next_step.get("skill") or "") == "external_test"
    )
    next_is_external_feature_extraction = (
        isinstance(next_step, dict)
        and str(next_step.get("skill") or "") == "feature_extraction"
        and str(next_step.get("id") or "") == "extract_external_features"
    )
    external_step_for_model = next_step if next_is_external else None
    if next_is_external_feature_extraction and next_index + 1 < len(steps):
        candidate = steps[next_index + 1]
        if isinstance(candidate, dict) and str(candidate.get("skill") or "") == "external_test":
            external_step_for_model = candidate
    if (
        skill == "external_test"
        or (
            skill != "feature_extraction"
            and (next_is_external or next_is_external_feature_extraction)
            and state.iteration_index >= state.max_iterations
        )
    ):
        if external_step_for_model is not None:
            inputs = external_step_for_model.setdefault("inputs", {})
            if (
                str(inputs.get("model_source") or "").lower() == "best_run"
                and not inputs.get("model_path")
            ):
                model_path = str((last_experiment or {}).get("model_path") or "")
                if model_path:
                    inputs["model_path"] = model_path
        plan["current_step"] = current + 1
        plan["steps"] = steps
        state.execution_plan = plan
        state.grounding["execution_plan"] = state.execution_plan
        if skill == "external_test":
            experiment = dict(last_experiment or {})
            record = {
                "run_id": str(experiment.get("run_id") or ""),
                "metrics": dict(experiment.get("metrics") or {}),
                "committed": bool(experiment.get("committed", True)),
                "model_path": str(experiment.get("model_path") or ""),
                "run_dir": str(experiment.get("run_dir") or ""),
                "status": "completed",
            }
            state.external_test = record
            state.external_test_history.append(record)
            state.stop_reason = state.stop_reason or "external_test_completed"
        return True
    return False


def _maybe_run_acquisition_for_missing_data(
    state: ResearchSessionState,
    session,
    config,
) -> ResearchSessionState:
    """Plan-2026-04-30 data-readiness Task 6 Step 6: when readiness
    surfaces ``missing_data`` and the plan is ``needs_acquisition``,
    invoke the acquisition stage once, then re-run readiness.

    Idempotent: a sentinel under
    ``state.grounding["data_acquisition_attempted_for_readiness"]``
    prevents repeated acquisition retries on resume.
    """
    plan = state.execution_plan or {}
    if plan.get("status") != "needs_acquisition":
        return state
    if not bool(getattr(config, "auto_acquire_data", False)):
        return state
    if (state.grounding or {}).get("data_acquisition_attempted_for_readiness"):
        # Already tried once; mark the plan blocked and stop trying.
        state.execution_plan = {
            **plan,
            "status": "blocked",
            "notes": list(plan.get("notes") or []) + [
                "acquisition/download was already attempted for missing data",
            ],
        }
        state.grounding["execution_plan"] = state.execution_plan
        return state

    state.grounding["data_acquisition_attempted_for_readiness"] = True
    suffix = "local data missing; trying acquisition/download chain"
    state.acquisition_notes = (
        (state.acquisition_notes + "; " if state.acquisition_notes else "") + suffix
    )
    state = _run_acquisition_stage(state, session, config)
    return _prepare_data_readiness_and_execution_plan(state, session, config)


# Subdirectory names that imply "this is the asset folder of a dataset" —
# i.e. ``<dataset_root>/<one_of_these>/`` is where raw assets live, and
# the parent is the dataset root where features should accompany them.
# ``WSIs`` is the canonical WSI folder; ``slides`` covers legacy prepared-MIL
# output (``<prepared>/slides/``);
# ``images`` covers patch datasets / kaggle-style ``train_images``.
_DATASET_ASSET_SUBDIRS = frozenset({
    "wsis", "wsi", "images", "image", "tiles", "raw",
    "slides",
})

_NESTED_DATASET_ASSET_SUBDIRS = frozenset({
    "train_images", "test_images", "validation_images", "val_images",
    "train", "test", "validation", "val",
})


def _dataset_root_from_asset_path(asset_path: Path) -> Path | None:
    """Return ``<dataset_root>`` for known raw asset folder shapes."""
    asset_path = Path(asset_path)
    name = asset_path.name.lower()
    if (
        name in _NESTED_DATASET_ASSET_SUBDIRS
        and asset_path.parent.name.lower() in _DATASET_ASSET_SUBDIRS
        and asset_path.parent.parent != asset_path.parent
    ):
        return asset_path.parent.parent
    if name in _NESTED_DATASET_ASSET_SUBDIRS and asset_path.parent != asset_path:
        return asset_path.parent
    if name in _DATASET_ASSET_SUBDIRS and asset_path.parent != asset_path:
        return asset_path.parent
    return None


def _dataset_root_from_manifest_raw_root(raw_root: Path) -> Path:
    """Return the durable dataset root described by an acquisition manifest."""
    raw_root = Path(raw_root)
    dataset_root = _dataset_root_from_asset_path(raw_root)
    if dataset_root is not None:
        return dataset_root
    if (
        raw_root.parent.name.lower() == "prepared"
        and raw_root.parent.parent != raw_root.parent
    ):
        return raw_root.parent.parent
    return raw_root


def _resolve_symlinked_asset_root(asset_dir: Path) -> Path | None:
    """Return the real dataset root when prepared assets symlink to raw cache."""
    try:
        if asset_dir.is_symlink():
            target_dir = asset_dir.resolve(strict=False)
            dataset_root = _dataset_root_from_asset_path(target_dir)
            if dataset_root is not None:
                return dataset_root

        roots: dict[Path, int] = {}
        for child in sorted(asset_dir.iterdir(), key=lambda p: p.name):
            if not child.is_symlink():
                continue
            target = child.resolve(strict=False)
            target_asset_dir = target.parent
            dataset_root = _dataset_root_from_asset_path(target_asset_dir)
            if dataset_root is None:
                dataset_root = target_asset_dir
            roots[dataset_root] = roots.get(dataset_root, 0) + 1
            if len(roots) > 1:
                return None
    except OSError:
        return None

    if not roots:
        return None
    if len(roots) > 1:
        return None
    return max(roots.items(), key=lambda item: (item[1], str(item[0])))[0]


def _resolve_features_data_output_dir(
    *, workspace_root, wsi_dir: str, raw_root: str = "",
) -> Path:
    """Pick the directory where feature_extraction should drop pt_files.

    DC-3 (2026-05-10): when WSIs live at a recognizable
    ``<dataset_root>/WSIs/`` (or ``images/`` / legacy ``slides/``) —
    i.e. the path's last segment looks like a raw asset
    folder — features go to ``<dataset_root>/pt_files/<extractor>/``
    so they sit alongside the data they were extracted from. This
    makes features durable across sessions (same dataset, same extractor
    subdirectory → reuse) and matches the dataset-centric layout used by
    acquisition.

    Falls back to ``<workspace>/.dataset/generated_features/`` when
    the WSI dir doesn't follow the convention — we don't want to
    scatter features into arbitrary user dirs.

    Important: the caller MUST pass the **host** path (e.g.
    ``/project/.../PANDA/WSIs``), not the container path (``/data/WSIs``).
    Container paths get rejected because they would land features under
    ``/data`` which isn't writable by the agent's tool process.
    """
    from pathlib import Path as _P

    workspace_root = _P(workspace_root)
    fallback = workspace_root / ".dataset" / "generated_features"
    if raw_root:
        raw_path = _P(raw_root)
        if not (str(raw_path).startswith("/data/") or str(raw_path) == "/data"):
            return _dataset_root_from_manifest_raw_root(raw_path)
    if not wsi_dir:
        return fallback
    p = _P(wsi_dir)
    # Reject container-shaped paths: ``/data/...`` and other obvious
    # mount points that aren't real host dirs.
    if str(p).startswith("/data/") or str(p) == "/data":
        return fallback
    dataset_root = _dataset_root_from_asset_path(p)
    if dataset_root is not None:
        symlink_root = _resolve_symlinked_asset_root(p)
        if symlink_root is not None:
            return symlink_root
        return dataset_root
    return fallback


def _inject_data_mounts_from_question(state, config) -> None:
    """Detect absolute paths in the user's question and inject existing
    directories into ``config.data_mounts`` so acquisition can be
    skipped naturally when the user supplied data inline.

    P0-A fix (session_858e8a2cdc49): the user wrote
    ``/project/compath/.../CRC-MSI`` (typo'd prefix) inline in the
    question. ``runtime/path_aliases.py`` already knew how to correct
    the typo, but nothing wired the corrected path into
    ``config.data_mounts`` — so the acquisition gate at line 415 saw
    an empty mount dict, fired discovery, picked NCT-CRC-HE-100K (a
    9-class colorectal *tissue type* dataset, not the user's MSI
    binary), and downloaded 29 GB of the wrong data.

    Idempotent: if ``config.data_mounts`` is already non-empty (user
    supplied via CLI / env), this is a no-op — we never override
    explicit configuration.

    Container path convention: ``/data/<lower(basename)>``. This matches
    the existing acquisition-side wiring and gives the agent a stable
    in-sandbox path regardless of host directory structure.
    """
    if getattr(config, "data_mounts", None):
        return
    question = (state.objective.question or "").strip()
    if not question:
        return

    from ..runtime.path_aliases import find_existing_data_paths

    paths = find_existing_data_paths(question)
    if not paths:
        return

    if not isinstance(getattr(config, "data_mounts", None), dict):
        config.data_mounts = {}

    injected: list[str] = []
    used_containers: set[str] = set()
    for host in paths:
        from pathlib import Path as _P
        base = _P(host).name.lower() or "data"
        container = f"/data/{base}"
        # Disambiguate if multiple paths share a basename.
        suffix = 1
        while container in used_containers:
            suffix += 1
            container = f"/data/{base}_{suffix}"
        used_containers.add(container)
        config.data_mounts[host] = container
        injected.append(host)

    if injected:
        state.grounding["data_mounts_source"] = "from_prompt"
        state.grounding["data_mounts_paths"] = list(injected)
        logger.info(
            "Injected data_mounts from prompt: %s",
            ", ".join(injected),
        )


def _safe_cache_mount_name(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or "dataset"


def _cache_readiness_mounts(cache_dir: str | Path, *, max_children: int = 128) -> dict[str, str]:
    """Return bounded mounts for probing the persistent dataset cache.

    Readiness probes conventional paths one mount root at a time. Mounting the
    unified cache root and its immediate children lets it find
    ``<cache>/<dataset>/pt_files/<extractor>`` before any dataset has been
    selected by acquisition.
    """
    root = Path(cache_dir).expanduser() if cache_dir else Path("")
    if not root.is_dir():
        return {}
    mounts: dict[str, str] = {str(root): "/data/cache"}
    try:
        children = sorted(
            (p for p in root.iterdir() if p.is_dir()),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return mounts
    added = 0
    for child in children:
        if added >= max_children:
            break
        if child.name.startswith("."):
            continue
        mounts[str(child)] = f"/data/{_safe_cache_mount_name(child.name)}"
        added += 1
    return mounts


def _config_proxy_with_data_mounts(config, data_mounts: dict[str, str]):
    payload = dict(getattr(config, "__dict__", {}) or {})
    proxy = SimpleNamespace(**payload)
    proxy.data_mounts = data_mounts
    return proxy


def _host_path_from_mounts(path_text: str, data_mounts: dict[str, str]) -> Path | None:
    text = str(path_text or "").strip()
    if not text:
        return None
    direct = Path(text).expanduser()
    if direct.exists():
        return direct
    for host_root, container_root in sorted(
        (data_mounts or {}).items(),
        key=lambda item: len(str(item[1] or "")),
        reverse=True,
    ):
        container = str(container_root or "").rstrip("/")
        if not container:
            continue
        if text == container or text.startswith(container + "/"):
            suffix = text[len(container):].lstrip("/")
            host = Path(host_root).expanduser()
            return host / suffix if suffix else host
    return None


def _slug_dataset_name(value: str) -> str:
    import re

    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip().lower())
    return slug.strip("-") or "dataset"


def _internal_explicit_dataset_paths(state, config) -> list[tuple[Path, str]]:
    """Return user-locked internal dataset roots from the external contract.

    The LLM decides dataset roles in ``external_request``. This helper only
    maps those role-tagged paths back to host paths already present in
    ``config.data_mounts``.
    """
    data_mounts = dict(getattr(config, "data_mounts", {}) or {})
    if not data_mounts:
        return []

    contracts: list[dict[str, Any]] = []
    request = (state.grounding or {}).get("external_test_request")
    if isinstance(request, dict):
        contract = request.get("contract")
        if isinstance(contract, dict):
            contracts.append(contract)
    explicit_contract = getattr(config, "external_test_contract", {}) or {}
    if isinstance(explicit_contract, dict):
        contracts.append(explicit_contract)

    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for contract in contracts:
        normalized = normalize_external_test_contract(contract or {})
        for item in normalized.get("datasets") or []:
            if not isinstance(item, dict) or item.get("role") != "internal":
                continue
            dataset_name = str(item.get("dataset_name") or "internal").strip()
            for raw_path in item.get("paths") or []:
                host = _host_path_from_mounts(str(raw_path), data_mounts)
                if host is None or not host.exists() or not host.is_dir():
                    continue
                resolved = host.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                out.append((host, dataset_name or host.name))
    return out


def _prepare_explicit_internal_dataset_if_possible(
    state: ResearchSessionState,
    session,
    config,
    *,
    profile,
) -> ResearchSessionState | None:
    """Prepare a user-supplied internal WSI folder without registry expansion."""
    if (state.grounding or {}).get("data_mounts_source") != "from_prompt":
        return None
    if getattr(profile, "task_type", "") != "mil_classification":
        return None

    internal_paths = _internal_explicit_dataset_paths(state, config)
    if not internal_paths:
        return None

    raw_root, dataset_name = internal_paths[0]
    try:
        from ..dataset.normalizers import MILClassificationNormalizer

        workspace_root = Path(session.workspace_dir)
        prepared_root = workspace_root / ".dataset" / "explicit_internal"
        contract = MILClassificationNormalizer().prepare(raw_root, prepared_root)
        if not contract.get("wsi_dir") or not contract.get("labels_file"):
            return None
    except Exception as exc:
        logger.info("explicit internal dataset preparation skipped: %s", exc)
        return None

    existing_mounts = dict(getattr(config, "data_mounts", {}) or {})
    remounted: dict[str, str] = {
        str(prepared_root): "/data",
        str(raw_root): "/data/raw",
    }
    for host, container in existing_mounts.items():
        if str(Path(host).expanduser()) in {str(prepared_root), str(raw_root)}:
            continue
        remounted[host] = container
    config.data_mounts = remounted

    state.grounding["explicit_internal_dataset_contract"] = dict(contract)
    state.grounding["explicit_internal_dataset_root"] = str(raw_root)
    state.selected_dataset = {
        "dataset_id": f"explicit:{_slug_dataset_name(dataset_name or raw_root.name)}",
        "name": dataset_name or raw_root.name,
        "provider": "local",
        "access": "local",
        "license": "",
    }
    refreshed = _prepare_data_readiness_and_execution_plan(state, session, config)
    if (refreshed.data_readiness or {}).get("status") in {
        "features_ready",
        "raw_wsi_ready",
        "not_applicable",
    }:
        refreshed.acquisition_status = "skipped"
        refreshed.acquisition_notes = (
            "explicit user-supplied internal dataset prepared; acquisition skipped"
        )
        return refreshed
    return None


def _cache_mounts_covering_ready_features(
    mounts: dict[str, str],
    readiness: dict,
) -> dict[str, str]:
    host_paths = [
        readiness.get("features_dir_host", ""),
        readiness.get("splits_file_host", ""),
    ]
    selected: dict[str, str] = {}
    for raw_path in host_paths:
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser()
        for host_root, container_root in sorted(
            mounts.items(),
            key=lambda item: len(str(item[0] or "")),
            reverse=True,
        ):
            root = Path(host_root).expanduser()
            try:
                path.resolve().relative_to(root.resolve())
            except (OSError, ValueError):
                continue
            selected[str(root)] = container_root
            break
    return selected


def _skip_acquisition_if_cache_features_ready(
    state: ResearchSessionState,
    session,
    config,
) -> ResearchSessionState | None:
    """Skip download when persistent features + splits are already complete."""
    cache_mounts = _cache_readiness_mounts(
        getattr(config, "dataset_cache_dir", "") or "",
    )
    if not cache_mounts:
        return None

    existing_mounts = dict(getattr(config, "data_mounts", {}) or {})
    probe_mounts = dict(existing_mounts)
    probe_mounts.update(cache_mounts)
    probe_config = _config_proxy_with_data_mounts(config, probe_mounts)
    _prepare_data_readiness_and_execution_plan(state, session, probe_config)
    if (state.data_readiness or {}).get("status") != "features_ready":
        return None

    ready_mounts = _cache_mounts_covering_ready_features(
        cache_mounts,
        state.data_readiness or {},
    ) or cache_mounts
    if not isinstance(getattr(config, "data_mounts", None), dict):
        config.data_mounts = {}
    config.data_mounts.update(ready_mounts)
    if hasattr(config, "planned_data_output_dir"):
        config.planned_data_output_dir = getattr(
            probe_config,
            "planned_data_output_dir",
            "",
        )
    state.acquisition_status = "skipped"
    state.acquisition_notes = (
        "existing complete feature cache found in dataset_cache_dir; "
        "raw-slide download skipped"
    )
    state.grounding["data_cache_readiness_mounts"] = ready_mounts
    return state


def _registry_record_keys(record) -> set[str]:
    """Stable duplicate keys for merging current seed records with cache."""
    keys: set[str] = set()
    dataset_id = str(getattr(record, "dataset_id", "") or "").strip().lower()
    name = str(getattr(record, "name", "") or "").strip().lower()
    if dataset_id:
        keys.add(f"id:{dataset_id}")
    if name:
        keys.add(f"name:{name}")
    for tag in getattr(record, "tags", []) or []:
        tag_key = str(tag or "").strip().lower()
        if tag_key:
            keys.add(f"tag:{tag_key}")
    return keys


def _merge_seed_and_cache_records(seed_records, cache_records):
    """Current seed wins over stale cache, while cache-only records survive."""
    out = list(seed_records or [])
    blocked: set[str] = set()
    for record in out:
        blocked |= _registry_record_keys(record)
    for record in cache_records or []:
        keys = _registry_record_keys(record)
        if keys and keys & blocked:
            continue
        out.append(record)
        blocked |= keys
    return out


def _run_acquisition_stage(
    state: ResearchSessionState,
    session,
    config,
) -> ResearchSessionState:
    """Run the dataset acquisition service when enabled.

    If ``config.data_mounts`` already has entries the user has supplied a
    prepared dataset path — the stage records ``acquisition_status='skipped'``
    and returns without invoking the registry. If grounding never produced a
    ``task_profile`` the stage records ``failed`` and returns. Otherwise the
    stage builds a :class:`DatasetAcquisitionService`, calls ``.acquire()``,
    and copies the result onto:

      * ``state.acquisition_status`` / ``state.acquisition_notes``
      * ``state.dataset_manifest_path``
      * ``state.selected_dataset`` (when a candidate was chosen)
      * ``config.data_mounts`` (so the OpenHands runtime mounts the dataset)

    Mutates ``state`` and ``config.data_mounts`` in place; returns ``state``.
    Never raises — failures are surfaced via ``acquisition_status='failed'``
    so the runner can still advance to execution if the user wants to.
    """
    # Plan-2026-04-30 data-readiness Task 6 / Step 7: replace blind
    # data_mounts skip with readiness-aware skip. For slide-level feature
    # consumers, even if user mounts exist, we must continue into
    # acquisition if those mounts don't actually contain features or raw
    # WSI + labels.
    if getattr(config, "data_mounts", None):
        local_state = _prepare_data_readiness_and_execution_plan(
            state, session, config,
        )
        local_status = (local_state.data_readiness or {}).get("status")
        if local_status in {"features_ready", "raw_wsi_ready", "not_applicable"}:
            state.data_readiness = local_state.data_readiness
            state.execution_plan = local_state.execution_plan
            state.acquisition_status = "skipped"
            state.acquisition_notes = (
                "user-supplied data_mounts are ready; acquisition skipped"
                if local_status != "not_applicable"
                else "user-supplied data_mounts; acquisition skipped"
            )
            return state
        # Fall through to acquisition: user mounts exist but readiness is
        # ``missing_data`` for a feature-consumer task. The user gave us a
        # path that doesn't satisfy the contract — try acquiring the rest.

    # Skip when grounding didn't produce a profile.
    profile_dict = (
        state.task_profile
        or (state.grounding or {}).get("task_profile")
        or {}
    )
    if not profile_dict:
        state.acquisition_status = "failed"
        state.acquisition_notes = "no task_profile in grounding"
        return state

    try:
        from ..dataset.types import TaskProfile as _TaskProfile

        explicit_profile = _TaskProfile.from_dict(profile_dict)
        explicit_state = _prepare_explicit_internal_dataset_if_possible(
            state,
            session,
            config,
            profile=explicit_profile,
        )
        if explicit_state is not None:
            return explicit_state
    except Exception as exc:
        logger.debug("explicit internal dataset path preparation unavailable: %s", exc)

    feature_cache_state = _skip_acquisition_if_cache_features_ready(
        state,
        session,
        config,
    )
    if feature_cache_state is not None:
        return feature_cache_state

    try:
        from pathlib import Path as _Path

        from ..dataset.acquisition import DatasetAcquisitionService
        from ..dataset.acquisition_plan import (
            acquisition_plan_path_for_workspace,
        )
        from ..dataset.discovery_extractor import extract_dataset_candidates
        from ..dataset.discovery_registry import merge_curated_and_discovered
        from ..dataset.discovery_store import (
            discovery_path_for_workspace,
            save_discovery_records,
        )
        from ..dataset.normalizers import (
            MILClassificationNormalizer,
            PatchClassificationNormalizer,
        )
        from ..dataset.policy import AcquisitionPolicy
        from ..dataset.providers import factory as _provider_factory
        from ..dataset.registry import DatasetRegistry
        from ..dataset.types import TaskProfile

        seed_path = (
            _Path(__file__).parent.parent
            / "dataset" / "seed_data" / "pathology_datasets.json"
        )
        cache_dir = getattr(config, "dataset_cache_dir", "") or ""
        # Plan-2026-04-30 dataset-discovery T7: even when a per-session
        # cache dir is configured, the curated seed JSON stays read-only.
        # We materialize a session-local merged registry into the workspace
        # so curated + discovered records can coexist without touching
        # ``dataset/seed_data/pathology_datasets.json``.
        seed_registry = DatasetRegistry(seed_path)
        if cache_dir:
            cache_registry_path = _Path(cache_dir) / "datasets.json"
            curated_registry = DatasetRegistry(cache_registry_path)
            if not cache_registry_path.exists():
                curated_registry.seed_from_json(seed_path)
            curated_records = _merge_seed_and_cache_records(
                seed_registry.load(),
                curated_registry.load(),
            )
        else:
            curated_registry = seed_registry
            curated_records = curated_registry.load()

        profile = TaskProfile.from_dict(profile_dict)

        # ---- Plan-2026-04-30 dataset-discovery T7: run extractor, persist,
        # ---- merge with curated, hand the merged registry to acquisition.
        workspace_root = _Path(session.workspace_dir)
        discovery_path = discovery_path_for_workspace(workspace_root)
        try:
            discovered = extract_dataset_candidates(state.grounding or {}, profile)
        except Exception as e:
            logger.warning("dataset discovery extraction failed: %s", e)
            discovered = []
        try:
            save_discovery_records(discovery_path, discovered)
        except Exception as e:
            logger.warning("dataset discovery persistence failed: %s", e)

        try:
            merged = merge_curated_and_discovered(curated_records, discovered)
        except Exception as e:
            logger.warning("merge_curated_and_discovered failed: %s", e)
            merged = curated_records

        session_registry_path = workspace_root / ".dataset" / "session_registry.json"
        session_registry = DatasetRegistry(session_registry_path)
        try:
            session_registry.save(merged)
        except Exception as e:
            logger.warning("session-local registry persist failed: %s", e)
            session_registry = curated_registry  # fallback

        # Surface paths for execution-brief consumers.
        state.grounding["dataset_discovery_path"] = str(discovery_path)
        state.grounding["dataset_acquisition_plan_path"] = str(
            acquisition_plan_path_for_workspace(workspace_root)
        )
        # Plan-2026-04-30 dataset-provider-repair Task 0 / blocker #2:
        # the merged session-local registry is the actual input the
        # acquisition service sees — surface the path so reviewers can
        # diff it against the curated seed.
        state.grounding["dataset_session_registry_path"] = str(session_registry_path)

        cache_root = (
            _Path(cache_dir) if cache_dir
            else _Path(session.persistence_root) / "datasets"
        )
        local_identity_llm_parser = None
        try:
            from ..runtime.metric_parser import build_llm_text_caller

            local_identity_llm_parser = build_llm_text_caller(config)
        except Exception as e:
            logger.debug("local identity LLM judge unavailable: %s", e)
        service = DatasetAcquisitionService(
            registry=session_registry,
            providers=_provider_factory.build_default_providers(),
            normalizers=[
                PatchClassificationNormalizer(),
                MILClassificationNormalizer(),
            ],
            cache_root=cache_root,
            policy=AcquisitionPolicy(
                download_policy=getattr(
                    config, "download_policy", "public_only",
                ),
                max_download_size_gb=getattr(
                    config, "max_download_size_gb", 20.0,
                ),
                allow_large_downloads=getattr(
                    config, "allow_large_downloads", False,
                ),
            ),
            local_identity_llm_parser=local_identity_llm_parser,
            download_only=(
                ((state.grounding or {}).get("stop_after_skill", "") or "").strip()
                == "acquisition"
            ),
        )

        result = service.acquire(profile, workspace_root=workspace_root)
    except Exception as e:
        logger.warning("Acquisition service failed: %s", e)
        state.acquisition_status = "failed"
        state.acquisition_notes = f"service_error:{e}"
        return state

    state.acquisition_status = result.status
    state.dataset_manifest_path = str(result.manifest_path)
    state.acquisition_notes = result.reason or ""
    if result.candidate is not None:
        record = result.candidate.record
        state.selected_dataset = {
            "dataset_id": record.dataset_id,
            "name": record.name,
            "provider": record.provider,
            "access": record.access,
            "license": record.license,
        }

    manifest_mounts = getattr(result.manifest, "data_mounts", None) or {}
    if manifest_mounts:
        if not isinstance(getattr(config, "data_mounts", None), dict):
            config.data_mounts = {}
        config.data_mounts.update(manifest_mounts)

    return state


def _stop_before_execution_enabled(config: PathScientistConfig) -> bool:
    """Return whether this run should stop before sending work to the code agent."""
    return bool(getattr(config, "stop_before_execution", False))


def _persist_execution_brief(state: ResearchSessionState, session) -> str:
    """Render and persist the exact brief that would be sent to the code agent."""
    brief = build_execution_brief(state)
    brief_dir = Path(session.workspace_dir) / ".pathscientist"
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_path = brief_dir / "execution_brief.md"
    brief_path.write_text(brief, encoding="utf-8")
    state.execution_brief = brief
    state.execution_brief_path = str(brief_path)
    state.grounding["execution_brief_path"] = str(brief_path)
    return brief


def _stop_before_execution(
    state: ResearchSessionState,
    session,
    conversation,
) -> ResearchSessionState:
    """Persist pre-execution artifacts and stop before any agent execution turn."""
    _persist_execution_brief(state, session)
    state.stop_reason = "stop_before_execution"
    if state.stage in {STAGE_EXECUTION, STAGE_ACQUISITION, STAGE_GROUNDING}:
        state.advance(STAGE_PRE_EXECUTION_READY)
    persist_research_session_state(conversation, state)
    logger.info(
        "Stop-before-execution requested; execution brief persisted at %s",
        state.execution_brief_path,
    )
    return state


def _paper_draft_generation_enabled(config: PathScientistConfig) -> bool:
    """Return whether synthesis should write paper_draft.md.

    Default remains enabled for direct Python callers. ``start.sh`` sets
    PATHSCIENTIST_GENERATE_PAPER_DRAFT=0 so normal bash launches skip this
    optional LLM/deterministic paper-writing step unless explicitly opted in.
    """
    import os

    raw = os.environ.get("PATHSCIENTIST_GENERATE_PAPER_DRAFT", "")
    if raw.strip():
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(getattr(config, "generate_paper_draft", True))


def _count_action_events_since(conversation, event_index: int) -> int:
    """Return number of ``ActionEvent`` instances since ``event_index``.

    An ``ActionEvent`` is emitted whenever the agent issues a tool call — any
    tool, including ``think`` / ``file_editor`` / ``validate_script`` /
    ``get_metrics``. A turn with zero new ``ActionEvent``s is one where the
    agent replied in text only and did not invoke any tool, i.e. it is
    genuinely idle. See Finding 6 of
    ``docs/review/2026-04-22-pathscientist-latest-run-review.md``.
    """
    try:
        from openhands.sdk.event import ActionEvent  # Lazy import keeps tests happy.

        events = list(conversation.state.events)[event_index:]
        return sum(1 for e in events if isinstance(e, ActionEvent))
    except Exception:
        # Safety net: if anything goes wrong introspecting the event log,
        # fall back to treating the turn as productive (0 idle) so we never
        # *falsely* kill a session. ``consecutive_non_finalized_turns`` is
        # still increased — so a truly frozen agent will still eventually
        # trip the higher threshold.
        return 1


def _bump_stall_counters(
    state: ResearchSessionState,
    *,
    idle: bool,
) -> None:
    """Update the two-counter stall tracking on a non-finalized turn.

    ``idle`` is True when the agent did not call any tool on this turn.
    ``state.stall_count`` is kept in sync as the max of the two counters
    so legacy consumers (``test_orchestrator_runner.py``, integrity reports,
    persisted older states) keep reading a meaningful value.
    """
    if idle:
        state.consecutive_idle_turns += 1
    else:
        state.consecutive_non_finalized_turns += 1
    state.stall_count = max(
        state.consecutive_idle_turns,
        state.consecutive_non_finalized_turns,
    )


def _reset_stall_counters(state: ResearchSessionState) -> None:
    """Reset all stall counters on a successful finalization."""
    state.consecutive_idle_turns = 0
    state.consecutive_non_finalized_turns = 0
    state.stall_count = 0


def _stall_limit_reached(state: ResearchSessionState) -> bool:
    """True if either stall counter has crossed its threshold."""
    return (
        state.consecutive_idle_turns >= MAX_IDLE_TURNS
        or state.consecutive_non_finalized_turns >= MAX_NON_FINALIZED_TURNS
    )


def _build_literature_store():
    """Create and seed the local literature store for Phase 3 grounding."""
    import os

    from ..literature.seed import seed_literature
    from ..literature.store import LiteratureStore

    lit_base = os.environ.get(
        "PATHSCIENTIST_BASE_DIR",
        DEFAULT_BASE_DIR,
    )
    lit_dir = Path(lit_base) / "literature"
    store = LiteratureStore(lit_dir)
    if not store.list_papers():
        seed_literature(store)
    return store


def _build_hybrid_retriever(config, literature_store):
    """Build a hybrid retriever from a local corpus directory."""
    import os

    from ..literature.chunk_store import ChunkStore
    from ..literature.embeddings import EmbeddingIndex
    from ..literature.hybrid_retriever import HybridLiteratureRetriever
    from ..literature.ingest import IngestManifest, ingest_document
    from ..literature.sparse_index import SparseChunkIndex

    lit_base = os.environ.get(
        "PATHSCIENTIST_BASE_DIR",
        DEFAULT_BASE_DIR,
    )
    lit_dir = Path(lit_base) / "literature"
    corpus_dir = config.literature_corpus_dir

    chunk_store = ChunkStore(lit_dir)
    manifest = IngestManifest(lit_dir / "corpus" / "manifests" / "ingest_state.json")

    # Ingest new/changed documents from corpus directory
    corpus_changed = False
    if corpus_dir and Path(corpus_dir).is_dir():
        for doc_path in sorted(Path(corpus_dir).iterdir()):
            if doc_path.suffix.lower() in (".txt", ".md", ".pdf") and manifest.should_reingest(doc_path):
                paper_id = doc_path.stem
                chunks = ingest_document(paper_id, doc_path)
                if chunks:
                    chunk_store.save_chunks(paper_id, chunks)
                    manifest.record(doc_path)
                    corpus_changed = True

    # Sparse index: rebuild only when corpus changed OR index is empty
    sparse_db_path = lit_dir / "corpus" / "sparse" / "fts.db"
    sparse_index = SparseChunkIndex(sparse_db_path)
    if corpus_changed or sparse_index.count() == 0 or sparse_index.needs_rebuild():
        sparse_index.rebuild(chunk_store)

    # Dense index: reuse on-disk artifacts when corpus unchanged
    dense_index = EmbeddingIndex(
        lit_dir / "corpus" / "dense",
        model_name=config.literature_rag_embedding_model,
        base_url=config.literature_rag_embedding_base_url,
        api_key=config.literature_rag_embedding_api_key,
    )
    dense_needs_rebuild = corpus_changed or (dense_index._matrix is None)
    if dense_needs_rebuild:
        all_chunks = list(chunk_store.iter_all_chunks())
        if all_chunks:
            dense_index.build(all_chunks)

    return HybridLiteratureRetriever(sparse_index, dense_index)


def _persist_grounding_citations(state: ResearchSessionState, tracker) -> None:
    """Persist the literature citations selected during grounding."""
    if tracker is None:
        return

    seen: set[str] = set()
    for citation in state.grounding.get("citations", []):
        paper_id = citation.get("paper_id", "")
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        tracker.cite(
            paper_id=paper_id,
            cited_in="execution_brief",
            context=citation.get("title", paper_id),
            conversation_id=str(state.conversation_id),
        )

    # Persist passage-level citations from RAG retrieval
    for passage in state.grounding.get("passages", []):
        paper_id = passage.get("paper_id", "")
        chunk_id = passage.get("chunk_id", "")
        if not paper_id or not chunk_id:
            continue
        tracker.cite(
            paper_id=paper_id,
            cited_in="execution_brief",
            context=passage.get("text", "")[:200],
            conversation_id=str(state.conversation_id),
            chunk_id=chunk_id,
            page=passage.get("page"),
            section=passage.get("section", ""),
            quote_snippet=passage.get("text", "")[:100],
        )


def _run_integrity_check(state: ResearchSessionState, deps) -> None:
    """Run IntegrityGuard against the current session and persist on state.

    Gathers tracker, iteration, run, workspace, and evidence inputs from
    ``SessionDeps`` + ``state``, calls ``check_session_integrity``, dumps the
    resulting ``IntegrityReport`` onto ``state.integrity_report``, logs each
    fatal issue as a warning, and forces ``state.paper_ready=False`` when any
    fatal issue is present. Never raises — invariant checks must not take
    down the runner; they report what went wrong for the user.

    Called just before ``_run_synthesis_stage`` in both
    ``run_research_session`` and ``continue_research_session`` so the
    synthesis output can include an ``## Integrity Issues`` section and so
    fatal session-level breakage forces ``paper_ready`` to ``False`` before
    verification/critique override it.
    """
    try:
        workspace = getattr(deps, "workspace", None)
        tracker = getattr(deps, "tracker", None)
        iteration_state = getattr(deps, "iteration_state", None)
        config = getattr(deps, "config", None)

        workspace_root = Path(getattr(workspace, "root", ".")) if workspace else Path(".")
        evidence_root = workspace_root / ".evidence"

        tracker_history = list(getattr(tracker, "history", []) or [])
        iteration_history = list(getattr(iteration_state, "history", []) or [])
        research_run_history = [asdict(r) for r in state.run_history]

        evidence_skipped_runs = list(getattr(deps, "evidence_skipped_runs", []) or [])
        primary_metric = (
            getattr(config, "primary_metric", "") or state.objective.success_metric or "auc"
        )

        report = check_session_integrity(
            workspace_root=workspace_root,
            evidence_root=evidence_root,
            tracker_history=tracker_history,
            iteration_history=iteration_history,
            research_run_history=research_run_history,
            max_iterations=state.max_iterations,
            iteration_index=state.iteration_index,
            stop_reason=state.stop_reason,
            evidence_skipped_runs=evidence_skipped_runs,
            primary_metric=primary_metric,
        )
    except Exception as exc:
        logger.warning(f"IntegrityGuard failed to run: {exc}")
        state.integrity_report = {
            "passed": False,
            "fatal_count": 0,
            "warning_count": 0,
            "issues": [],
            "error": str(exc),
        }
        return

    state.integrity_report = report.to_dict()

    for issue in report.issues:
        if issue.severity == "fatal":
            logger.warning(
                "[integrity] FATAL %s: %s", issue.code, issue.message
            )
        else:
            logger.info(
                "[integrity] %s %s: %s", issue.severity, issue.code, issue.message
            )

    if report.fatal_count > 0:
        if state.paper_ready:
            logger.warning(
                "IntegrityGuard reported %d fatal issue(s); forcing paper_ready=False.",
                report.fatal_count,
            )
        state.paper_ready = False


def run_research_session(
    config: PathScientistConfig,
    question: str,
    auto_approve: bool = True,
    visualizer=None,
    progress_callback: ProgressCallback | None = None,
) -> ResearchSessionState:
    """Run a full research session through the orchestrator.

    Creates an agent, advances through stages, and returns the final state.
    """
    from ..agent import create_agent, create_conversation
    from ..runtime.session_registry import get_session

    # Create agent and conversation
    agent, workspace, tracker, session = create_agent(config, research_question=question)
    conversation = create_conversation(agent, workspace, session, visualizer=visualizer)

    logger.info(f"Research session started: {session.conversation_id}")
    logger.info(f"  Question: {question}")

    # Initialize orchestrator state
    objective = ResearchObjective(
        question=question,
        success_metric=config.primary_metric,
        preferred_skill=config.skill_name,
    )
    state = ResearchSessionState.create(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        objective=objective,
    )
    state.max_iterations = config.max_iterations
    _notify_progress(progress_callback, state)

    # Initialize literature store and citation tracker.
    # Two-level storage contract:
    #   - LiteratureStore is GLOBAL under {BASE_DIR}/literature/ (shared corpus)
    #   - CitationTracker is CONVERSATION-SCOPED under {persistence_root}/{conv_hex}/
    literature_store = None
    citation_tracker = None
    try:
        from ..literature.citations import CitationTracker

        literature_store = _build_literature_store()
        citation_tracker = CitationTracker(session.persistence_root)
    except Exception as e:
        logger.warning(f"Literature store unavailable: {e}")

    # Initialize passage-level RAG retriever (when enabled)
    literature_retriever = None
    if config.literature_rag_enabled and literature_store:
        try:
            literature_retriever = _build_hybrid_retriever(config, literature_store)
        except Exception as e:
            logger.warning(f"RAG retriever unavailable: {e}")

    # Initialize online literature clients (when enabled).
    # Plan-2026-04-29 literature-acquisition Phase 1 / Task 3: share the
    # OpenAlex client with SOTA benchmark extraction via the session-scoped
    # factory.
    online_clients: list = []
    if config.literature_online_enabled:
        try:
            from ..literature.online_clients import (
                get_or_create_online_client,
            )
            provider_names = list(
                getattr(config, "literature_online_providers", []) or []
            ) or [config.literature_online_provider]
            for provider in provider_names:
                online_clients.append(
                    get_or_create_online_client(
                        provider=provider,
                        timeout=config.literature_online_timeout,
                        session_id=getattr(session, "session_id", "") or "",
                    )
                )
            logger.info(
                "Online literature search enabled: %s",
                ",".join(provider_names),
            )
        except Exception as e:
            logger.warning(f"Online literature client unavailable: {e}")

    # Initialize evidence store (workspace-scoped)
    evidence_store = None
    try:
        from ..evidence.store import EvidenceStore
        evidence_store = EvidenceStore(workspace.root / ".evidence")
    except Exception as e:
        logger.warning(f"Evidence store unavailable: {e}")

    sota_lookup = _build_sota_lookup(session, config, literature_store)

    # Plan-2026-04-29 literature-acquisition Phase 1 / Task 8: build a
    # NetworkPolicy from legacy config flags and forward to director so
    # ground_objective gates paper search / SOTA / RAG dense uniformly.
    from ..runtime.network_policy import network_policy_from_config
    network_policy = network_policy_from_config(config)
    # Phase 2 / Task 6: session-scoped paper cache.
    paper_cache = _build_paper_cache(session)
    # Phase 5 / Task 4: session-scoped PaperRegistry for auto-ingest.
    paper_registry = _build_paper_registry(session)
    # Phase 4 / Task 6: unified LiteratureService.
    literature_service = _build_literature_service(
        literature_store=literature_store,
        online_clients=online_clients,
        sota_lookup=sota_lookup,
        literature_retriever=literature_retriever,
        paper_cache=paper_cache,
        network_policy=network_policy,
        paper_registry=paper_registry,
        config=config,
    )

    director = ResearchDirector(
        auto_approve=auto_approve,
        llm_model=config.llm_model,
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url,
        llm_config=config,
        literature_store=literature_store,
        literature_retriever=literature_retriever,
        rag_top_k=config.literature_rag_top_k,
        online_clients=online_clients,
        sota_lookup=sota_lookup,
        enable_acquisition=bool(getattr(config, "auto_acquire_data", False)),
        network_policy=network_policy,
        paper_cache=paper_cache,
        literature_service=literature_service,
    )

    # Advance: intake -> grounding
    state = director.advance(state)
    _notify_progress(progress_callback, state)
    # Advance: grounding -> execution (or acquisition, or pending approval)
    state = director.advance(state)
    _notify_progress(progress_callback, state)

    # P0-A fix (2026-05-01): if the user mentioned an existing local
    # data path inline in their question (with optional typo correction
    # via KNOWN_PREFIX_ALIASES), inject it into config.data_mounts NOW
    # — before the acquisition gate. Without this, session_858e8a2cdc49
    # downloaded 29 GB of NCT-CRC-HE-100K (wrong dataset) even though
    # the user supplied ``/project/compath/.../CRC-MSI`` inline.
    _inject_data_mounts_from_question(state, config)

    if state.approval_status == "pending":
        _persist_grounding_citations(state, citation_tracker)
        persist_research_session_state(conversation, state)
        if auto_approve:
            logger.info("Batch mode: auto-approving grounding plan")
            state.approval_status = "approved"
            state = director.advance(state)
            _notify_progress(progress_callback, state)
        else:
            logger.info("Manual approval required; returning paused grounding state")
            return state, session, conversation
    else:
        _persist_grounding_citations(state, citation_tracker)
        persist_research_session_state(conversation, state)

    # If routed into acquisition, run the service then advance to execution.
    if state.stage == STAGE_ACQUISITION:
        _notify_progress(progress_callback, state)
        state = _run_acquisition_stage(state, session, config)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)
        state = director.advance(state)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)

    # Plan-2026-04-30 data-readiness review P0-1: assess readiness +
    # build execution plan + maybe run acquisition fallback BEFORE entering
    # the execution loop. ``blocked`` and ``needs_acquisition`` plans must
    # short-circuit with ``stop_reason="data_missing"`` rather than letting
    # the agent train on missing data.
    if state.stage == STAGE_EXECUTION:
        state.advance(STAGE_PRE_EXECUTION_READY)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)
        state = _prepare_data_readiness_and_execution_plan(state, session, config)
        state = _maybe_run_acquisition_for_missing_data(state, session, config)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)
        plan_status = (state.execution_plan or {}).get("status")
        if plan_status == "stopped_after_acquisition":
            state.stop_reason = "stop_after_acquisition"
            _persist_execution_brief(state, session)
            persist_research_session_state(conversation, state)
            _notify_progress(progress_callback, state)
            return state, session, conversation
        if plan_status in {"blocked", "needs_acquisition"}:
            state.stop_reason = "data_missing"
            _persist_execution_brief(state, session)
            persist_research_session_state(conversation, state)
            _notify_progress(progress_callback, state)
            return state, session, conversation

    if state.stage == STAGE_PRE_EXECUTION_READY and _stop_before_execution_enabled(config):
        state = _stop_before_execution(state, session, conversation)
        _notify_progress(progress_callback, state)
        return state, session, conversation
    if state.stage == STAGE_PRE_EXECUTION_READY:
        state.advance(STAGE_EXECUTION)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)

    # Execution loop
    while state.stage == STAGE_EXECUTION:
        # Stall detection — Finding 6 (2026-04-22 review):
        # OLD rule: ``stall_count`` incremented on every non-finalized turn,
        # so normal post-commit ``think → edit → validate`` work hit the
        # limit of 2 almost immediately.
        # NEW rule: two separate counters, thresholds tuned to the intent —
        # idle (no ActionEvent at all) is tight, working-but-not-ratcheting
        # is generous enough for the real workflow.
        if _stall_limit_reached(state):
            logger.warning(
                "Stall limit reached "
                "(idle=%d/%d, non_finalized=%d/%d). Forcing session to synthesis.",
                state.consecutive_idle_turns, MAX_IDLE_TURNS,
                state.consecutive_non_finalized_turns, MAX_NON_FINALIZED_TURNS,
            )
            state.stop_reason = "stall_limit"
            state.advance("review")
            run_review_stage(
                state,
                previous_best_value=state.best_metric_value,
                previous_run_count=len(state.run_history),
                action_events=0,
            )
            state = director.advance(state)  # stop_reason triggers review -> synthesis
            persist_research_session_state(conversation, state)
            break

        logger.info(
            f"Execution iteration {state.iteration_index + 1}/{state.max_iterations}"
        )
        _notify_progress(progress_callback, state)

        # Snapshot tracker history length + event log length before agent runs
        deps = get_session(session.session_id)
        history_len_before = len(deps.tracker.history) if deps.tracker else 0
        external_test_len_before = len(getattr(deps, "external_test_history", []) or [])
        events_len_before = len(conversation.state.events)
        previous_best_value = state.best_metric_value
        previous_run_count = len(state.run_history)
        action_events = 0
        dropped_entries = 0

        # Build and send execution brief
        _sync_planned_feature_extraction_env_from_current_step(state, config)
        brief = build_execution_brief(state)
        conversation.send_message(brief)
        conversation.run()

        # Plan-2026-04-30 data-readiness review P0-2: feature_extraction is
        # data setup, not a metric-bearing iteration. If the current step
        # produced .pt files, advance the plan and skip RunRecord
        # processing for this turn.
        if _current_execution_skill(state) == "feature_extraction":
            from pathlib import Path as _Path
            deps_for_workspace = get_session(session.session_id)
            workspace_root = _Path(
                getattr(getattr(deps_for_workspace, "workspace", None), "root", None)
                or session.workspace_dir
            )
            if _advance_execution_plan_after_iteration(
                state, workspace_root=workspace_root,
            ):
                persist_research_session_state(conversation, state)
                _notify_progress(progress_callback, state)
                continue

        # Check if agent finalized an iteration (via ratchet_commit or ratchet_revert)
        deps = get_session(session.session_id)
        history_len_after = len(deps.tracker.history) if deps.tracker else 0
        external_test_len_after = len(getattr(deps, "external_test_history", []) or [])
        action_events = _count_action_events_since(
            conversation, events_len_before,
        )

        if history_len_after > history_len_before:
            # Record ALL newly finalized iterations (usually 1, but handle >1)
            # but CAP at max_iterations so a single agent turn that fires many
            # ratchet_commit calls cannot push iteration_index past budget.
            # Before this cap, session_b14b074d2268 reached iteration_index=17
            # with max_iterations=5 because the agent ratcheted 17 times in one
            # ``conversation.run()`` and the runner faithfully incremented on
            # each entry. The director only sees this at review-entry — far
            # too late to stop the overrun from being recorded.
            from .metrics_utils import resolve_primary_metric
            new_entries = deps.tracker.history[history_len_before:]

            processed = 0
            for entry in new_entries:
                if state.iteration_index >= state.max_iterations:
                    break

                raw_metrics = entry.get("metrics", {}) if isinstance(entry, dict) else {}
                metric_value = resolve_primary_metric(raw_metrics, state.objective.success_metric)
                committed = entry.get("committed", False) if isinstance(entry, dict) else False

                # Read canonical run_id from the tracker history entry itself
                run_id = entry.get("run_id", "") if isinstance(entry, dict) else ""
                if not run_id:
                    run_id = f"run_{state.iteration_index}"

                state.record_run(RunRecord(
                    run_id=run_id,
                    iteration=state.iteration_index,
                    metric_name=state.objective.success_metric,
                    metric_value=metric_value,
                    committed=committed,
                ))
                state.iteration_index += 1
                processed += 1
            _reset_stall_counters(state)  # Reset on successful finalization

            dropped = len(new_entries) - processed
            dropped_entries = dropped
            if dropped > 0 and not state.stop_reason:
                logger.warning(
                    "Agent finalized beyond budget (max_iterations=%d) in a "
                    "single turn; dropped %d extra ratchet entries and "
                    "halting with stop_reason='budget_exhausted'.",
                    state.max_iterations,
                    dropped,
                )
                state.stop_reason = "budget_exhausted"
            if processed > 0:
                _advance_execution_plan_after_metric_step(
                    state,
                    last_experiment=getattr(deps, "last_experiment", {}) or {},
                )
        elif external_test_len_after > external_test_len_before:
            external_entries = (getattr(deps, "external_test_history", []) or [])[
                external_test_len_before:
            ]
            external_payload = dict(external_entries[-1]) if external_entries else {}
            _advance_execution_plan_after_metric_step(
                state,
                last_experiment=external_payload,
            )
            _reset_stall_counters(state)
        else:
            # Agent did not finalize — either fully idle (no tool calls
            # at all) or working without ratcheting. The two-counter scheme
            # treats these differently so a normal think/edit/validate
            # sequence does not immediately trip the guard.
            idle = action_events == 0
            _bump_stall_counters(state, idle=idle)
            if idle:
                logger.warning(
                    "Agent turn had zero tool activity "
                    "(idle %d/%d, non_finalized %d/%d)",
                    state.consecutive_idle_turns, MAX_IDLE_TURNS,
                    state.consecutive_non_finalized_turns, MAX_NON_FINALIZED_TURNS,
                )
            else:
                logger.info(
                    "Agent turn did not finalize but called %d tool(s) "
                    "(idle %d/%d, non_finalized %d/%d)",
                    action_events,
                    state.consecutive_idle_turns, MAX_IDLE_TURNS,
                    state.consecutive_non_finalized_turns, MAX_NON_FINALIZED_TURNS,
                )

        # Advance: execution -> review
        state.advance("review")
        run_review_stage(
            state,
            previous_best_value=previous_best_value,
            previous_run_count=previous_run_count,
            action_events=action_events,
            dropped_entries=dropped_entries,
        )
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)

        # Director decides: review -> execution (loop) or review -> synthesis (stop)
        state = director.advance(state)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)

    # Synthesis — build structured report + markdown + optional paper draft
    if state.stage == STAGE_SYNTHESIS:
        # Safety net: even if the director was bypassed or state was resumed
        # mid-transition, a budget overrun must carry a stop_reason into
        # synthesis so orchestrator history and IntegrityGuard can audit it.
        if state.iteration_index > state.max_iterations and not state.stop_reason:
            logger.warning(
                "iteration_index (%d) > max_iterations (%d) entering synthesis "
                "with no stop_reason; forcing 'budget_exhausted'",
                state.iteration_index,
                state.max_iterations,
            )
            state.stop_reason = "budget_exhausted"
        # IntegrityGuard: run BEFORE synthesis so report_builder sees the
        # report and can append an "Integrity Issues" section.
        deps = get_session(session.session_id)
        _run_integrity_check(state, deps)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)
        state = _run_synthesis_stage(
            state, workspace, session, config,
            evidence_store=evidence_store,
            citation_tracker=citation_tracker,
            deps=deps,
        )
        state.final_summary = build_session_summary(
            state, evidence_store=evidence_store, citation_tracker=citation_tracker,
        )
        state.ui_run_summary = build_ui_run_summary(state, config)
        _notify_progress(progress_callback, state)
        state = director.advance(state)
        persist_research_session_state(conversation, state)
        _notify_progress(progress_callback, state)

    logger.info(f"Research session completed: {session.conversation_id}")
    if state.best_run_id:
        logger.info(f"  Best: {state.best_run_id} ({state.best_metric_value:.4f})")
    logger.info(f"  Summary:\n{state.final_summary}")

    return state, session, conversation


def continue_research_session(
    config: PathScientistConfig,
    state: ResearchSessionState,
    session,
    conversation,
    auto_approve: bool = True,
) -> ResearchSessionState:
    """Continue a paused research session (e.g. after /approve).

    Re-enters the orchestrator from the current state, advancing through
    grounding -> execution -> synthesis as needed.
    """
    from ..runtime.session_registry import get_session

    # Re-initialize literature/evidence stores
    literature_store = None
    citation_tracker = None
    try:
        from ..literature.citations import CitationTracker
        literature_store = _build_literature_store()
        citation_tracker = CitationTracker(session.persistence_root)
    except Exception:
        pass

    evidence_store = None
    try:
        from ..evidence.store import EvidenceStore
        deps = get_session(session.session_id)
        if deps.workspace:
            evidence_store = EvidenceStore(deps.workspace.root / ".evidence")
    except Exception:
        pass

    sota_lookup = _build_sota_lookup(session, config, literature_store)

    # Plan-2026-04-29 literature-acquisition Phase 1 / Task 8.
    from ..runtime.network_policy import network_policy_from_config
    network_policy = network_policy_from_config(config)
    paper_cache = _build_paper_cache(session)
    # Phase 5 / Task 4: load existing PaperRegistry from prior sessions.
    paper_registry = _build_paper_registry(session)
    # Phase 4 / Task 6 — service for continue path. ``literature_retriever``
    # is None on resume (no RAG retriever rebuilt for continue); service
    # still wraps paper search + SOTA.
    literature_service = _build_literature_service(
        literature_store=literature_store,
        online_clients=[],
        sota_lookup=sota_lookup,
        literature_retriever=None,
        paper_cache=paper_cache,
        network_policy=network_policy,
        paper_registry=paper_registry,
        config=config,
    )

    director = ResearchDirector(
        auto_approve=auto_approve,
        llm_model=config.llm_model,
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url,
        llm_config=config,
        literature_store=literature_store,
        sota_lookup=sota_lookup,
        enable_acquisition=bool(getattr(config, "auto_acquire_data", False)),
        network_policy=network_policy,
        paper_cache=paper_cache,
        literature_service=literature_service,
    )

    # Advance from current stage (grounding with approval -> execution
    # or -> acquisition when enable_acquisition=True).
    if state.stage == STAGE_GROUNDING:
        state = director.advance(state)
        if state.stage == STAGE_COMPLETED:
            persist_research_session_state(conversation, state)
            return state, session, conversation
        _persist_grounding_citations(state, citation_tracker)
        persist_research_session_state(conversation, state)

    # P0-A fix (mirror of run_research_session): inject data_mounts from
    # the user's prompt path (with alias correction) before acquisition
    # gate fires, so a resumed session honors the same inline-path
    # contract.
    _inject_data_mounts_from_question(state, config)

    # If routed into acquisition (either by this advance or because we
    # resumed mid-acquisition), run the service and advance to execution.
    if state.stage == STAGE_ACQUISITION:
        state = _run_acquisition_stage(state, session, config)
        persist_research_session_state(conversation, state)
        state = director.advance(state)
        persist_research_session_state(conversation, state)

    # Plan-2026-04-30 data-readiness review P0-1: mirror of run_research_session.
    if state.stage == STAGE_EXECUTION:
        state.advance(STAGE_PRE_EXECUTION_READY)
        persist_research_session_state(conversation, state)
        state = _prepare_data_readiness_and_execution_plan(state, session, config)
        state = _maybe_run_acquisition_for_missing_data(state, session, config)
        persist_research_session_state(conversation, state)
        plan_status = (state.execution_plan or {}).get("status")
        if plan_status == "stopped_after_acquisition":
            state.stop_reason = "stop_after_acquisition"
            _persist_execution_brief(state, session)
            persist_research_session_state(conversation, state)
            return state, session, conversation
        if plan_status in {"blocked", "needs_acquisition"}:
            state.stop_reason = "data_missing"
            _persist_execution_brief(state, session)
            persist_research_session_state(conversation, state)
            return state, session, conversation

    if state.stage == STAGE_PRE_EXECUTION_READY and _stop_before_execution_enabled(config):
        state = _stop_before_execution(state, session, conversation)
        return state, session, conversation
    if state.stage == STAGE_PRE_EXECUTION_READY:
        state.advance(STAGE_EXECUTION)
        persist_research_session_state(conversation, state)

    # Execution loop (same as run_research_session)
    workspace = get_session(session.session_id).workspace

    while state.stage == STAGE_EXECUTION:
        # Stall detection (Finding 6) — see matching comment in
        # ``run_research_session``.
        if _stall_limit_reached(state):
            state.stop_reason = "stall_limit"
            state.advance("review")
            run_review_stage(
                state,
                previous_best_value=state.best_metric_value,
                previous_run_count=len(state.run_history),
                action_events=0,
            )
            state = director.advance(state)
            persist_research_session_state(conversation, state)
            break

        deps = get_session(session.session_id)
        history_len_before = len(deps.tracker.history) if deps.tracker else 0
        external_test_len_before = len(getattr(deps, "external_test_history", []) or [])
        events_len_before = len(conversation.state.events)
        previous_best_value = state.best_metric_value
        previous_run_count = len(state.run_history)
        action_events = 0
        dropped_entries = 0

        _sync_planned_feature_extraction_env_from_current_step(state, config)
        brief = build_execution_brief(state)
        conversation.send_message(brief)
        conversation.run()

        # Plan-2026-04-30 data-readiness review P0-2: same setup-vs-iteration
        # rule as run_research_session. feature_extraction setup advances
        # WITHOUT touching iteration_index / RunRecord history.
        if _current_execution_skill(state) == "feature_extraction":
            from pathlib import Path as _Path
            deps_for_workspace = get_session(session.session_id)
            workspace_root = _Path(
                getattr(getattr(deps_for_workspace, "workspace", None), "root", None)
                or session.workspace_dir
            )
            if _advance_execution_plan_after_iteration(
                state, workspace_root=workspace_root,
            ):
                persist_research_session_state(conversation, state)
                continue

        deps = get_session(session.session_id)
        history_len_after = len(deps.tracker.history) if deps.tracker else 0
        external_test_len_after = len(getattr(deps, "external_test_history", []) or [])
        action_events = _count_action_events_since(
            conversation, events_len_before,
        )

        if history_len_after > history_len_before:
            # Cap iteration processing at max_iterations so a single agent turn
            # that fires many ratchet_commit calls cannot push iteration_index
            # past budget (see the matching comment in run_research_session).
            from .metrics_utils import resolve_primary_metric
            new_entries = deps.tracker.history[history_len_before:]
            processed = 0
            for entry in new_entries:
                if state.iteration_index >= state.max_iterations:
                    break
                raw_metrics = entry.get("metrics", {}) if isinstance(entry, dict) else {}
                metric_value = resolve_primary_metric(raw_metrics, state.objective.success_metric)
                committed = entry.get("committed", False) if isinstance(entry, dict) else False
                run_id = entry.get("run_id", "") if isinstance(entry, dict) else ""
                if not run_id:
                    run_id = f"run_{state.iteration_index}"
                state.record_run(RunRecord(
                    run_id=run_id,
                    iteration=state.iteration_index,
                    metric_name=state.objective.success_metric,
                    metric_value=metric_value,
                    committed=committed,
                ))
                state.iteration_index += 1
                processed += 1
            _reset_stall_counters(state)

            dropped = len(new_entries) - processed
            dropped_entries = dropped
            if dropped > 0 and not state.stop_reason:
                logger.warning(
                    "Agent finalized beyond budget (max_iterations=%d) in a "
                    "single turn; dropped %d extra ratchet entries and "
                    "halting with stop_reason='budget_exhausted'.",
                    state.max_iterations,
                    dropped,
                )
                state.stop_reason = "budget_exhausted"
            if processed > 0:
                _advance_execution_plan_after_metric_step(
                    state,
                    last_experiment=getattr(deps, "last_experiment", {}) or {},
                )
        elif external_test_len_after > external_test_len_before:
            external_entries = (getattr(deps, "external_test_history", []) or [])[
                external_test_len_before:
            ]
            external_payload = dict(external_entries[-1]) if external_entries else {}
            _advance_execution_plan_after_metric_step(
                state,
                last_experiment=external_payload,
            )
            _reset_stall_counters(state)
        else:
            _bump_stall_counters(state, idle=(action_events == 0))

        state.advance("review")
        run_review_stage(
            state,
            previous_best_value=previous_best_value,
            previous_run_count=previous_run_count,
            action_events=action_events,
            dropped_entries=dropped_entries,
        )
        persist_research_session_state(conversation, state)
        state = director.advance(state)
        persist_research_session_state(conversation, state)

    if state.stage == STAGE_SYNTHESIS:
        # Safety net: mirrors run_research_session. A budget overrun reaching
        # synthesis without a stop_reason must be annotated here.
        if state.iteration_index > state.max_iterations and not state.stop_reason:
            logger.warning(
                "iteration_index (%d) > max_iterations (%d) entering synthesis "
                "with no stop_reason; forcing 'budget_exhausted'",
                state.iteration_index,
                state.max_iterations,
            )
            state.stop_reason = "budget_exhausted"
        # IntegrityGuard: run BEFORE synthesis so report_builder sees the
        # report and can append an "Integrity Issues" section.
        try:
            deps = get_session(session.session_id)
        except KeyError:
            deps = None
        if deps is not None:
            _run_integrity_check(state, deps)
            persist_research_session_state(conversation, state)
        state = _run_synthesis_stage(
            state, workspace, session, config,
            evidence_store=evidence_store,
            citation_tracker=citation_tracker,
            deps=deps,
        )
        state.final_summary = build_session_summary(
            state, evidence_store=evidence_store, citation_tracker=citation_tracker,
        )
        state.ui_run_summary = build_ui_run_summary(state, config)
        state = director.advance(state)
        persist_research_session_state(conversation, state)

    return state, session, conversation


def _run_synthesis_stage(
    state: ResearchSessionState,
    workspace,
    session,
    config: PathScientistConfig,
    evidence_store=None,
    citation_tracker=None,
    deps=None,
) -> ResearchSessionState:
    """Run the synthesis stage: build report + markdown + optional paper draft.

    ``deps`` is the session's :class:`SessionDeps` (optional for backward
    compatibility with older call sites / tests). When provided, Review Fix C
    (2026-04-21 post-fix code review, Finding 3) consults
    ``deps.evidence_skipped_runs`` and forces ``state.paper_ready=False`` if
    any entry has ``reason == "external_experiment_opt_in"``. IntegrityGuard
    keeps that case as a warning (not fatal) — we're gating the product
    output, not escalating severity.
    """
    from ..synthesis.context import build_synthesis_context
    from ..synthesis.report_builder import build_report, render_report_markdown
    from ..synthesis.store import ReportStore

    # Build synthesis context
    context = build_synthesis_context(
        state,
        evidence_store=evidence_store,
        citation_tracker=citation_tracker,
    )

    # Build structured report
    integrity_report = dict(state.integrity_report or {})
    report = build_report(context, integrity_report=integrity_report)

    # Render markdown
    markdown = render_report_markdown(report)

    # Save artifacts
    report_store = ReportStore(workspace.root / ".reports")
    report_json_path = str(report_store.save(report))
    report_md_path = str(report_store.save_markdown(state.session_id, markdown))

    # Optional: paper draft
    paper_draft_path = ""
    draft = ""
    if _paper_draft_generation_enabled(config):
        try:
            from ..synthesis.paper_writer import build_paper_draft
            draft = build_paper_draft(
                report,
                llm_model=config.llm_model,
                llm_api_key=config.llm_api_key,
                llm_base_url=config.llm_base_url,
                config=config,
            )
            paper_draft_path = str(
                report_store.save_markdown(
                    state.session_id, draft, "paper_draft.md",
                )
            )
        except Exception as e:
            logger.warning(f"Paper draft generation failed: {e}")
    else:
        logger.info("Paper draft generation disabled.")

    # Persist grounded section inputs
    grounded_sections_path = ""
    try:
        from ..synthesis.grounding import build_grounded_section_inputs
        grounded_sections = build_grounded_section_inputs(report)
        grounded_sections_path = str(
            report_store.save_grounded_sections(state.session_id, grounded_sections)
        )
    except Exception as e:
        logger.warning(f"Grounded section persistence failed: {e}")

    # Verify and critique paper draft
    verification_path = ""
    critique_path = ""
    verification_passed = False
    verification_issue_count = 0
    critique_issue_count = 0
    paper_ready = False

    if paper_draft_path:
        try:
            from ..synthesis.verification import verify_paper_draft
            from ..synthesis.critique import critique_paper_draft

            # Plan-2026-04-28 P0 #2: at the paper_ready gate, require
            # substantive content in addition to lineage. Bare-headings
            # drafts (session_d162f805e1d7) must NOT pass.
            verification = verify_paper_draft(
                report, draft, enforce_substantive_content=True,
            )
            critique = critique_paper_draft(report, draft)

            verification_path = str(report_store.save_verification(state.session_id, verification))
            critique_path = str(report_store.save_critique(state.session_id, critique))
            verification_passed = verification.passed
            verification_issue_count = verification.issue_count
            critique_issue_count = critique.issue_count
            paper_ready = verification.passed and not critique.requires_revision

            logger.info(f"Verification: {'PASSED' if verification.passed else 'FAILED'} ({verification.issue_count} issues)")
            logger.info(f"Critique: {'PASSED' if critique.passed else f'{critique.issue_count} issues'}")
        except Exception as e:
            logger.warning(f"Paper verification/critique failed: {e}")

    # Integrity gate: a fatal integrity issue means the session was broken
    # (no git commits, blank run_ids, missing evidence, etc.). Paper is not
    # ready regardless of what verification/critique said.
    fatal_integrity = int(integrity_report.get("fatal_count", 0) or 0) > 0
    if fatal_integrity:
        if paper_ready:
            logger.warning(
                "IntegrityGuard reported fatal issues; forcing paper_ready=False."
            )
        paper_ready = False

    # Review Fix C: external_experiment_opt_in still lets agent bypass evidence.
    # IntegrityGuard keeps it as warning (expected), but paper must not be marked
    # ready — the paper has at least one committed run without evidence backing.
    # See docs/review/2026-04-21-pathscientist-post-fix-code-review-results.md
    # (Finding 3, Option 2). Severity stays warning; only product output is gated.
    # Evaluated before manifest save so manifest, state, and report.json stay
    # consistent.
    external_opt_in_used = any(
        (skip or {}).get("reason") == "external_experiment_opt_in"
        for skip in (getattr(deps, "evidence_skipped_runs", None) or [])
    )
    if external_opt_in_used and paper_ready:
        logger.warning(
            "Session used RatchetAction.external=True for at least one run; "
            "forcing paper_ready=False so unsupported commits do not ship as "
            "ready-to-read papers. IntegrityGuard severity remains warning."
        )
        paper_ready = False

    # Save manifest
    report_store.save_manifest(state.session_id, {
        "report_json": report_json_path,
        "report_markdown": report_md_path,
        "paper_draft": paper_draft_path,
        "paper_verification": verification_path,
        "paper_critique": critique_path,
        "grounded_sections": grounded_sections_path,
        "claim_count": len(report.claims),
        "paper_ready": paper_ready,
    })

    # Update state with synthesis artifact paths
    state.report_json_path = report_json_path
    state.report_markdown_path = report_md_path
    state.paper_draft_path = paper_draft_path
    state.claim_count = len(report.claims)
    state.paper_verification_path = verification_path
    state.paper_verification_passed = verification_passed
    state.paper_verification_issue_count = verification_issue_count
    state.paper_critique_path = critique_path
    state.paper_critique_issue_count = critique_issue_count
    state.paper_ready = paper_ready

    # Re-save report.json with correct output paths
    report.report_markdown_path = report_md_path
    report.paper_draft_path = paper_draft_path
    report_store.save(report)

    logger.info(f"Synthesis complete: {report_md_path}")
    if paper_draft_path:
        logger.info(f"Paper draft: {paper_draft_path} (ready={paper_ready})")

    return state
