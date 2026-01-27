"""
Analysis graph: simple tool-based agent for result analysis.
No confirmation flow needed - analysis can be run directly.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .tool import (
    get_analysis_stats_tool,
    get_task_analysis_tool,
    list_analysis_tasks_tool,
    run_task_analysis_tool,
)


# Analysis tools - all available for direct use
ANALYSIS_TOOLS = [
    list_analysis_tasks_tool,
    run_task_analysis_tool,
    get_task_analysis_tool,
    get_analysis_stats_tool,
]

ANALYSIS_AGENT_PROMPT = """You help users analyze training task results: list available tasks, run analysis, view analysis history, and get quick statistics.

Analysis workflow:
1. Use list_analysis_tasks to see which completed training tasks are available for analysis
2. Use run_task_analysis to run comprehensive analysis (generates metrics and charts)
3. Use get_task_analysis to view analysis history for a task
4. Use get_analysis_stats to quickly check statistics without running full analysis

Tools:
- list_analysis_tasks: list training tasks that are available for result analysis. Only completed tasks with both features and models are shown. Optionally filter by data_level (wsi or patch). Tasks without AI results need to run inference first.
- run_task_analysis: run comprehensive analysis on a completed training task. Generates metrics (accuracy, precision, recall, F1, AUC for classification; C-Index for survival) and charts (ROC curve, confusion matrix, loss curve for classification; KM curve for survival). Results are saved to logs/analysis/{task_id}/{timestamp}/. The task must be completed and have AI results.
- get_task_analysis: get analysis history for a training task. Returns all previous analysis runs with their metrics and timestamps. Use this to check if an analysis already exists before running a new one.
- get_analysis_stats: get quick analysis statistics for predictions without running full analysis. Returns overall metrics and per-class metrics. Useful for quick checks. For detailed analysis with charts, use run_task_analysis instead.

Note: Analysis requires the task to be completed and have AI results. If a task has no AI results, the user needs to run inference first (not handled by this agent).

Reply in the same language as the user."""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AnalysisState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _analysis_agent_node(state: AnalysisState, llm: BaseChatModel) -> dict:
    """Main agent node that decides which tool to use."""
    messages = state.get("messages", [])
    
    # Add system prompt if not present
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=ANALYSIS_AGENT_PROMPT)] + messages
    
    # Get LLM response with tool calling
    response = llm.bind_tools(ANALYSIS_TOOLS).invoke(messages)
    
    return {"messages": [response]}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def create_analysis_graph(llm: BaseChatModel | None = None):
    """
    Create the analysis agent graph.
    - llm: None 时从 backend.agent.llm.get_llm 获取。
    - 输入 state：messages
    - 环境：GATEWAY_SERVICE_URL（tools 用）。
    """
    if llm is None:
        from backend.agent.llm import get_llm
        _llm = get_llm()
    else:
        _llm = llm
    
    tool_node = ToolNode(ANALYSIS_TOOLS)
    
    def agent_node(s: AnalysisState) -> dict:
        return _analysis_agent_node(s, _llm)
    
    graph = StateGraph(AnalysisState)
    
    # Add nodes
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    
    # Add edges
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        lambda state: _should_continue(state),
        {
            "continue": "tools",
            "end": END,
        },
    )
    graph.add_edge("tools", "agent")
    
    return graph.compile()


def _should_continue(state: AnalysisState) -> str:
    """Determine if we should continue to tools or end."""
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    
    # If last message has tool calls, continue to tools
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "continue"
    
    # Otherwise end
    return "end"
