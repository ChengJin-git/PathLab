"""Research director — lightweight state machine for session stage transitions."""
from __future__ import annotations

import logging

from .grounding import ground_objective
from .types import (
    STAGE_ACQUISITION,
    STAGE_COMPLETED,
    STAGE_EXECUTION,
    STAGE_GROUNDING,
    STAGE_INTAKE,
    STAGE_REVIEW,
    STAGE_SYNTHESIS,
    ResearchSessionState,
)

logger = logging.getLogger(__name__)


class ResearchDirector:
    """Decides what stage a research session should be in next.

    The director does NOT execute anything — it only advances state.
    The runner is responsible for acting on the state.
    """

    def __init__(
        self,
        auto_approve: bool = True,
        llm_model: str = "",
        llm_api_key: str = "",
        llm_base_url: str = "",
        literature_store=None,
        literature_retriever=None,
        rag_top_k: int = 3,
        online_clients: list | None = None,
        sota_lookup=None,
        llm_parser=None,
        enable_acquisition: bool = False,
    ):
        self.auto_approve = auto_approve
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.literature_store = literature_store
        self.literature_retriever = literature_retriever
        self.rag_top_k = rag_top_k
        self.online_clients = online_clients or []
        self.sota_lookup = sota_lookup
        self.llm_parser = llm_parser
        self.enable_acquisition = enable_acquisition

    def advance(self, state: ResearchSessionState) -> ResearchSessionState:
        """Advance the session to the next appropriate stage.

        Returns the same state object (mutated in place).
        """
        if state.stage == STAGE_INTAKE:
            state.advance(STAGE_GROUNDING)
            logger.info(f"Director: intake -> grounding")
            return state

        if state.stage == STAGE_GROUNDING:
            # Populate grounding if not already done
            if not state.grounding:
                state.grounding = ground_objective(
                    state.objective,
                    llm_model=self.llm_model,
                    llm_api_key=self.llm_api_key,
                    llm_base_url=self.llm_base_url,
                    literature_store=self.literature_store,
                    literature_retriever=self.literature_retriever,
                    rag_top_k=self.rag_top_k,
                    online_clients=self.online_clients,
                    sota_lookup=self.sota_lookup,
                    llm_parser=self.llm_parser,
                )
                # Copy grounding-discovered dataset hint and SOTA target
                # payload onto state.objective. grounding.py itself stays
                # pure — the director owns all state mutation.
                dataset_hint = state.grounding.get("dataset_hint_inferred", "")
                if dataset_hint and not state.objective.dataset_hint:
                    state.objective.dataset_hint = dataset_hint
                target_payload = state.grounding.get("sota_target") or {}
                if target_payload:
                    state.objective.target_metric_value = float(
                        target_payload.get("metric_value", 0.0) or 0.0
                    )
                    paper_id = target_payload.get("paper_id", "")
                    paper_title = target_payload.get("paper_title", "")
                    state.objective.target_source = (
                        f"{paper_id} — {paper_title}"
                        if paper_title else paper_id
                    )
                    state.objective.target_confidence = target_payload.get(
                        "confidence", ""
                    )

            # Copy the grounding-emitted task_profile (T1) onto state so the
            # acquisition stage can read it without going through grounding
            # again, and so persisted state preserves it.
            grounded_profile = (state.grounding or {}).get("task_profile")
            if grounded_profile and not state.task_profile:
                state.task_profile = dict(grounded_profile)

            if not self.auto_approve:
                if state.approval_status == "approved":
                    next_stage = (
                        STAGE_ACQUISITION
                        if self.enable_acquisition else STAGE_EXECUTION
                    )
                    state.advance(next_stage)
                    logger.info(
                        "Director: grounding -> %s (approved)", next_stage,
                    )
                    return state
                if state.approval_status == "rejected":
                    state.stop_reason = "approval_rejected"
                    state.advance(STAGE_COMPLETED)
                    logger.info("Director: grounding -> completed (rejected)")
                    return state
                # Not yet decided — stay in grounding, mark pending
                state.approval_status = "pending"
                logger.info("Director: grounding complete, waiting for approval")
                return state

            state.approval_status = "none"
            if self.enable_acquisition:
                state.advance(STAGE_ACQUISITION)
                logger.info("Director: grounding -> acquisition")
            else:
                state.advance(STAGE_EXECUTION)
                logger.info("Director: grounding -> execution")
            return state

        if state.stage == STAGE_ACQUISITION:
            state.advance(STAGE_EXECUTION)
            logger.info(
                "Director: acquisition -> execution (status=%s)",
                state.acquisition_status,
            )
            return state

        if state.stage == STAGE_REVIEW:
            if state.stop_reason or state.iteration_index >= state.max_iterations:
                # Preserve any explicit stop_reason already on the state
                # (e.g. "user_cancelled", "stall_limit", "approval_rejected");
                # only fall back to "budget_exhausted" when nothing is set and
                # the iteration budget is the cause of the transition.
                if not state.stop_reason:
                    state.stop_reason = "budget_exhausted"
                state.advance(STAGE_SYNTHESIS)
                logger.info(f"Director: review -> synthesis ({state.stop_reason})")
            else:
                state.advance(STAGE_EXECUTION)
                logger.info(
                    f"Director: review -> execution "
                    f"(iteration {state.iteration_index}/{state.max_iterations})"
                )
            return state

        if state.stage == STAGE_SYNTHESIS:
            state.advance(STAGE_COMPLETED)
            logger.info("Director: synthesis -> completed")
            return state

        return state
