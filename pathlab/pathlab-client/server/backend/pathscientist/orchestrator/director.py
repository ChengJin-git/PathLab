"""Research director — lightweight state machine for session stage transitions."""
from __future__ import annotations

import logging

from .grounding import ground_objective
from .types import (
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
                    state,
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

            if not self.auto_approve:
                if state.approval_status == "approved":
                    state.advance(STAGE_EXECUTION)
                    logger.info("Director: grounding -> execution (approved)")
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
            state.advance(STAGE_EXECUTION)
            logger.info("Director: grounding -> execution")
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
