"""
Analysis tools: built on the Results Analysis API (Gateway /results).

Layout:
  analysis/
    src/analysis/   <- tool, graph
    tests/
    run_chat.py     <- REPL test tool calls

- list_analysis_tasks: list tasks available for analysis (completed tasks with features and models)
- run_task_analysis: run comprehensive analysis on a task (metrics + charts)
- get_task_analysis: get analysis history for a task
- get_analysis_stats: get quick analysis statistics without running full analysis
"""

from .src.analysis import (
    create_analysis_graph,
    get_analysis_stats_tool,
    get_task_analysis_tool,
    list_analysis_tasks_tool,
    run_task_analysis_tool,
    GetAnalysisStatsInput,
    GetTaskAnalysisInput,
    ListAnalysisTasksInput,
    RunTaskAnalysisInput,
)

__all__ = [
    "create_analysis_graph",
    "list_analysis_tasks_tool",
    "run_task_analysis_tool",
    "get_task_analysis_tool",
    "get_analysis_stats_tool",
    "ListAnalysisTasksInput",
    "RunTaskAnalysisInput",
    "GetTaskAnalysisInput",
    "GetAnalysisStatsInput",
]
