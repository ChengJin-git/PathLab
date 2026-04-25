"""Research session runner — wraps the code agent with orchestrator stage management."""
from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from ..config import PathScientistConfig
from ..literature.benchmark_extractor import BenchmarkExtractor
from ..literature.pwc_client import PapersWithCodeClient
from ..literature.sota_cache import SotaCache
from ..literature.sota_lookup import SotaLookup
from ..orchestrator.director import ResearchDirector
from ..orchestrator.prompts import build_execution_brief
from ..orchestrator.state_bridge import persist_research_session_state
from ..orchestrator.summary import build_session_summary
from ..orchestrator.types import (
    MAX_IDLE_TURNS,
    MAX_NON_FINALIZED_TURNS,
    STAGE_ACQUISITION,
    STAGE_COMPLETED,
    STAGE_EXECUTION,
    STAGE_GROUNDING,
    STAGE_SYNTHESIS,
    ResearchObjective,
    ResearchSessionState,
    RunRecord,
)
from ..runtime.integrity import check_session_integrity

logger = logging.getLogger(__name__)


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
        if not offline:
            try:
                from ..literature.online_clients import create_online_client
                online = create_online_client("openalex")
            except Exception as e:
                logger.warning("SotaLookup: openalex client init failed: %s", e)
            try:
                from ..runtime.metric_parser import build_llm_metric_parser
                extractor = BenchmarkExtractor(
                    llm_parser=build_llm_metric_parser(config),
                )
            except Exception as e:
                logger.warning("SotaLookup: LLM extractor init failed: %s", e)
        return SotaLookup(
            store=literature_store,
            cache=SotaCache(cache_path),
            pwc_client=pwc,
            online_client=online,
            llm_extractor=extractor,
            offline=offline,
        )
    except Exception as e:
        logger.warning("SotaLookup construction failed: %s", e)
        return None


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
    # Skip when user already provided mounts.
    if getattr(config, "data_mounts", None):
        state.acquisition_status = "skipped"
        state.acquisition_notes = (
            "user-supplied data_mounts; acquisition skipped"
        )
        return state

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
        from pathlib import Path as _Path

        from ..dataset.acquisition import DatasetAcquisitionService
        from ..dataset.normalizers import (
            MILClassificationNormalizer,
            PatchClassificationNormalizer,
        )
        from ..dataset.policy import AcquisitionPolicy
        from ..dataset.providers.direct_http import DirectHTTPProvider
        from ..dataset.providers.huggingface import HuggingFaceProvider
        from ..dataset.providers.zenodo import ZenodoProvider
        from ..dataset.registry import DatasetRegistry
        from ..dataset.types import TaskProfile

        seed_path = (
            _Path(__file__).parent.parent
            / "dataset" / "seed_data" / "pathology_datasets.json"
        )
        cache_dir = getattr(config, "dataset_cache_dir", "") or ""
        registry_path = (
            _Path(cache_dir) / "datasets.json" if cache_dir else seed_path
        )
        registry = DatasetRegistry(registry_path)
        if not registry_path.exists():
            registry.seed_from_json(seed_path)

        cache_root = (
            _Path(cache_dir) if cache_dir
            else _Path(session.persistence_root) / "datasets"
        )
        service = DatasetAcquisitionService(
            registry=registry,
            providers={
                "direct_http": DirectHTTPProvider(),
                "zenodo": ZenodoProvider(),
                "huggingface": HuggingFaceProvider(),
            },
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
        )

        profile = TaskProfile.from_dict(profile_dict)
        result = service.acquire(profile, workspace_root=session.workspace_dir)
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
        "/project/vcompath/storage/ywangrm/tmp/pathscientist",
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
        "/project/vcompath/storage/ywangrm/tmp/pathscientist",
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

    # Initialize online literature clients (when enabled)
    online_clients: list = []
    if config.literature_online_enabled:
        try:
            from ..literature.online_clients import create_online_client
            client = create_online_client(
                provider=config.literature_online_provider,
                timeout=config.literature_online_timeout,
            )
            online_clients = [client]
            logger.info(f"Online literature search enabled: {config.literature_online_provider}")
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

    director = ResearchDirector(
        auto_approve=auto_approve,
        llm_model=config.llm_model,
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url,
        literature_store=literature_store,
        literature_retriever=literature_retriever,
        rag_top_k=config.literature_rag_top_k,
        online_clients=online_clients,
        sota_lookup=sota_lookup,
        enable_acquisition=bool(getattr(config, "auto_acquire_data", False)),
    )

    # Advance: intake -> grounding
    state = director.advance(state)
    # Advance: grounding -> execution (or acquisition, or pending approval)
    state = director.advance(state)

    if state.approval_status == "pending":
        _persist_grounding_citations(state, citation_tracker)
        persist_research_session_state(conversation, state)
        if auto_approve:
            logger.info("Batch mode: auto-approving grounding plan")
            state.approval_status = "approved"
            state = director.advance(state)
        else:
            logger.info("Manual approval required; returning paused grounding state")
            return state, session, conversation
    else:
        _persist_grounding_citations(state, citation_tracker)
        persist_research_session_state(conversation, state)

    # If routed into acquisition, run the service then advance to execution.
    if state.stage == STAGE_ACQUISITION:
        state = _run_acquisition_stage(state, session, config)
        persist_research_session_state(conversation, state)
        state = director.advance(state)
        persist_research_session_state(conversation, state)

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
            state = director.advance(state)  # stop_reason triggers review -> synthesis
            persist_research_session_state(conversation, state)
            break

        logger.info(
            f"Execution iteration {state.iteration_index + 1}/{state.max_iterations}"
        )

        # Snapshot tracker history length + event log length before agent runs
        deps = get_session(session.session_id)
        history_len_before = len(deps.tracker.history) if deps.tracker else 0
        events_len_before = len(conversation.state.events)

        # Build and send execution brief
        brief = build_execution_brief(state)
        conversation.send_message(brief)
        conversation.run()

        # Check if agent finalized an iteration (via ratchet_commit or ratchet_revert)
        deps = get_session(session.session_id)
        history_len_after = len(deps.tracker.history) if deps.tracker else 0

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
            if dropped > 0 and not state.stop_reason:
                logger.warning(
                    "Agent finalized beyond budget (max_iterations=%d) in a "
                    "single turn; dropped %d extra ratchet entries and "
                    "halting with stop_reason='budget_exhausted'.",
                    state.max_iterations,
                    dropped,
                )
                state.stop_reason = "budget_exhausted"
        else:
            # Agent did not finalize — either fully idle (no tool calls
            # at all) or working without ratcheting. The two-counter scheme
            # treats these differently so a normal think/edit/validate
            # sequence does not immediately trip the guard.
            action_events = _count_action_events_since(
                conversation, events_len_before,
            )
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
        persist_research_session_state(conversation, state)

        # Director decides: review -> execution (loop) or review -> synthesis (stop)
        state = director.advance(state)
        persist_research_session_state(conversation, state)

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
        state = _run_synthesis_stage(
            state, workspace, session, config,
            evidence_store=evidence_store,
            citation_tracker=citation_tracker,
            deps=deps,
        )
        state.final_summary = build_session_summary(
            state, evidence_store=evidence_store, citation_tracker=citation_tracker,
        )
        state = director.advance(state)
        persist_research_session_state(conversation, state)

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

    director = ResearchDirector(
        auto_approve=auto_approve,
        llm_model=config.llm_model,
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url,
        literature_store=literature_store,
        sota_lookup=sota_lookup,
        enable_acquisition=bool(getattr(config, "auto_acquire_data", False)),
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

    # If routed into acquisition (either by this advance or because we
    # resumed mid-acquisition), run the service and advance to execution.
    if state.stage == STAGE_ACQUISITION:
        state = _run_acquisition_stage(state, session, config)
        persist_research_session_state(conversation, state)
        state = director.advance(state)
        persist_research_session_state(conversation, state)

    # Execution loop (same as run_research_session)
    workspace = get_session(session.session_id).workspace

    while state.stage == STAGE_EXECUTION:
        # Stall detection (Finding 6) — see matching comment in
        # ``run_research_session``.
        if _stall_limit_reached(state):
            state.stop_reason = "stall_limit"
            state.advance("review")
            state = director.advance(state)
            persist_research_session_state(conversation, state)
            break

        deps = get_session(session.session_id)
        history_len_before = len(deps.tracker.history) if deps.tracker else 0
        events_len_before = len(conversation.state.events)

        brief = build_execution_brief(state)
        conversation.send_message(brief)
        conversation.run()

        deps = get_session(session.session_id)
        history_len_after = len(deps.tracker.history) if deps.tracker else 0

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
            if dropped > 0 and not state.stop_reason:
                logger.warning(
                    "Agent finalized beyond budget (max_iterations=%d) in a "
                    "single turn; dropped %d extra ratchet entries and "
                    "halting with stop_reason='budget_exhausted'.",
                    state.max_iterations,
                    dropped,
                )
                state.stop_reason = "budget_exhausted"
        else:
            action_events = _count_action_events_since(
                conversation, events_len_before,
            )
            _bump_stall_counters(state, idle=(action_events == 0))

        state.advance("review")
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
    try:
        from ..synthesis.paper_writer import build_paper_draft
        draft = build_paper_draft(
            report,
            llm_model=config.llm_model,
            llm_api_key=config.llm_api_key,
            llm_base_url=config.llm_base_url,
        )
        paper_draft_path = str(report_store.save_markdown(state.session_id, draft, "paper_draft.md"))
    except Exception as e:
        logger.warning(f"Paper draft generation failed: {e}")

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

            verification = verify_paper_draft(report, draft)
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
