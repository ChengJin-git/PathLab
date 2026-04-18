"""Research session runner — wraps the code agent with orchestrator stage management."""
from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from ..config import PathScientistConfig
from ..orchestrator.director import ResearchDirector
from ..orchestrator.prompts import build_execution_brief
from ..orchestrator.state_bridge import persist_research_session_state
from ..orchestrator.summary import build_session_summary
from ..orchestrator.types import (
    MAX_CONSECUTIVE_STALLS,
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

    director = ResearchDirector(
        auto_approve=auto_approve,
        llm_model=config.llm_model,
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url,
        literature_store=literature_store,
        literature_retriever=literature_retriever,
        rag_top_k=config.literature_rag_top_k,
        online_clients=online_clients,
    )

    # Advance: intake -> grounding
    state = director.advance(state)
    # Advance: grounding -> execution (populates grounding)
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

    # Execution loop
    while state.stage == STAGE_EXECUTION:
        # Stall detection: if agent failed to finalize N consecutive turns, abort
        if state.stall_count >= MAX_CONSECUTIVE_STALLS:
            logger.warning(
                f"Stall limit reached ({state.stall_count} consecutive "
                f"non-finalized turns). Forcing session to synthesis."
            )
            state.stop_reason = "stall_limit"
            state.advance("review")
            state = director.advance(state)  # stop_reason triggers review -> synthesis
            persist_research_session_state(conversation, state)
            break

        logger.info(
            f"Execution iteration {state.iteration_index + 1}/{state.max_iterations}"
        )

        # Snapshot tracker history length before agent runs
        deps = get_session(session.session_id)
        history_len_before = len(deps.tracker.history) if deps.tracker else 0

        # Build and send execution brief
        brief = build_execution_brief(state)
        conversation.send_message(brief)
        conversation.run()

        # Check if agent finalized an iteration (via ratchet_commit or ratchet_revert)
        deps = get_session(session.session_id)
        history_len_after = len(deps.tracker.history) if deps.tracker else 0

        if history_len_after > history_len_before:
            # Record ALL newly finalized iterations (usually 1, but handle >1)
            from .metrics_utils import resolve_primary_metric
            new_entries = deps.tracker.history[history_len_before:]

            for entry in new_entries:
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
            state.stall_count = 0  # Reset stall counter on successful finalization
        else:
            # Agent did not finalize — stuck, error, or no ratchet call
            # Do NOT consume iteration budget for non-finalized turns
            state.stall_count += 1
            logger.warning(
                f"Agent turn completed without finalizing an iteration "
                f"(stall {state.stall_count}/{MAX_CONSECUTIVE_STALLS})"
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

    director = ResearchDirector(
        auto_approve=auto_approve,
        llm_model=config.llm_model,
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url,
        literature_store=literature_store,
    )

    # Advance from current stage (grounding with approval -> execution)
    if state.stage == STAGE_GROUNDING:
        state = director.advance(state)
        if state.stage == STAGE_COMPLETED:
            persist_research_session_state(conversation, state)
            return state, session, conversation
        _persist_grounding_citations(state, citation_tracker)
        persist_research_session_state(conversation, state)

    # Execution loop (same as run_research_session)
    workspace = get_session(session.session_id).workspace

    while state.stage == STAGE_EXECUTION:
        if state.stall_count >= MAX_CONSECUTIVE_STALLS:
            state.stop_reason = "stall_limit"
            state.advance("review")
            state = director.advance(state)
            persist_research_session_state(conversation, state)
            break

        deps = get_session(session.session_id)
        history_len_before = len(deps.tracker.history) if deps.tracker else 0

        brief = build_execution_brief(state)
        conversation.send_message(brief)
        conversation.run()

        deps = get_session(session.session_id)
        history_len_after = len(deps.tracker.history) if deps.tracker else 0

        if history_len_after > history_len_before:
            from .metrics_utils import resolve_primary_metric
            new_entries = deps.tracker.history[history_len_before:]
            for entry in new_entries:
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
            state.stall_count = 0
        else:
            state.stall_count += 1

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
) -> ResearchSessionState:
    """Run the synthesis stage: build report + markdown + optional paper draft."""
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
