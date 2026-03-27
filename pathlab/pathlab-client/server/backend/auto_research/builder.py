"""
Auto Research Agent — Graph Builder

Constructs the LangGraph StateGraph with all 9 nodes and edges.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .types import AutoResearchState
from .nodes import (
    coordinator_node,
    literature_review_node,
    experiment_planner_node,
    human_review_node,
    experiment_executor_node,
    experiment_monitor_node,
    results_analyzer_node,
    iteration_router_node,
    reporter_node,
)


def build_auto_research_graph(checkpointer=None):
    """
    Build and compile the Auto Research Agent graph.

    Graph flow:
        START → coordinator → literature_review → experiment_planner
        → human_review → experiment_executor → experiment_monitor
        → results_analyzer → iteration_router
            ├→ reporter → END
            └→ experiment_planner (iterate)

    Args:
        checkpointer: LangGraph checkpointer for state persistence.
                      Defaults to MemorySaver (in-memory).

    Returns:
        Compiled LangGraph graph ready for invocation.
    """
    graph = StateGraph(AutoResearchState)

    # ── Register Nodes ────────────────────────────────────────────
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("literature_review", literature_review_node)
    graph.add_node("experiment_planner", experiment_planner_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("experiment_executor", experiment_executor_node)
    graph.add_node("experiment_monitor", experiment_monitor_node)
    graph.add_node("results_analyzer", results_analyzer_node)
    graph.add_node("iteration_router", iteration_router_node)
    graph.add_node("reporter", reporter_node)

    # ── Register Edges ────────────────────────────────────────────
    # Linear flow
    graph.add_edge(START, "coordinator")
    graph.add_edge("coordinator", "literature_review")
    graph.add_edge("literature_review", "experiment_planner")
    graph.add_edge("experiment_planner", "human_review")

    # human_review routes via Command (approved → executor, edit → planner)
    # No explicit conditional edge needed — Command.goto handles routing

    graph.add_edge("experiment_executor", "experiment_monitor")
    graph.add_edge("experiment_monitor", "results_analyzer")
    graph.add_edge("results_analyzer", "iteration_router")

    # iteration_router routes via Command (continue → planner, stop → reporter)
    # No explicit conditional edge needed — Command.goto handles routing

    graph.add_edge("reporter", END)

    # ── Compile ───────────────────────────────────────────────────
    if checkpointer is None:
        checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)
