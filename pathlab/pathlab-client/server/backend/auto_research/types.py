"""
Auto Research Agent — State Definition

Extends LangGraph's MessagesState with fields for the full research pipeline:
literature → planning → execution → monitoring → analysis → iteration → report.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional

from langgraph.graph import MessagesState


# Phase constants
PHASE_LITERATURE = "literature"
PHASE_PLANNING = "planning"
PHASE_REVIEW = "review"
PHASE_EXECUTING = "executing"
PHASE_MONITORING = "monitoring"
PHASE_ANALYZING = "analyzing"
PHASE_ROUTING = "routing"
PHASE_REPORTING = "reporting"

ALL_PHASES = [
    PHASE_LITERATURE,
    PHASE_PLANNING,
    PHASE_REVIEW,
    PHASE_EXECUTING,
    PHASE_MONITORING,
    PHASE_ANALYZING,
    PHASE_ROUTING,
    PHASE_REPORTING,
]


class AutoResearchState(MessagesState):
    """
    Full state for the Auto Research Agent graph.

    Uses LangGraph's MessagesState as base (provides `messages` with
    add_messages reducer for automatic message accumulation).
    """

    # ── Identity ──────────────────────────────────────────────────────
    locale: str = "en-US"
    research_question: str = ""

    # ── Literature Phase ──────────────────────────────────────────────
    # Each finding: {title, url, methods: [{extractor, aggregator, dataset, metrics}], summary}
    literature_findings: Annotated[list[dict], operator.add] = []

    # ── Planning Phase ────────────────────────────────────────────────
    # Discovered resources from PathLab API
    # {datasets: [...], extractors: [...], aggregators: [...], gpu_info: {...}}
    available_resources: dict = {}

    # Experiment plan: [{id, name, dataset_id, extractor, aggregator, hyperparams, rationale}]
    experiment_plan: list[dict] = []
    plan_approved: bool = False

    # ── Execution Phase ───────────────────────────────────────────────
    # {experiment_id: {training_task_id, config, status}}
    submitted_tasks: dict[str, dict] = {}

    # ── Results Phase ─────────────────────────────────────────────────
    # [{experiment_id, training_task_id, metrics: {accuracy, auc, f1, ...}}]
    completed_results: Annotated[list[dict], operator.add] = []
    failed_results: Annotated[list[dict], operator.add] = []

    # ── Analysis Phase ────────────────────────────────────────────────
    # {columns: [...], rows: [...], best_experiment_id: str}
    comparison_table: dict = {}
    analysis_summary: str = ""

    # ── Iteration Control (AutoResearch Ratchet) ──────────────────────
    iteration: int = 0
    max_iterations: int = 3
    best_metric: float = 0.0          # Ratchet baseline (e.g., best AUC)
    best_metric_name: str = "auc"     # Which metric to optimize
    best_experiment: dict = {}        # Current best experiment config
    # [{iteration, experiment_id, metric_value, improved: bool}]
    improvement_history: Annotated[list[dict], operator.add] = []

    # ── Control ───────────────────────────────────────────────────────
    phase: str = PHASE_LITERATURE
    stop_requested: bool = False
    final_report: str = ""


@dataclass
class AutoResearchConfig:
    """Per-session configuration for the auto research agent."""

    max_iterations: int = 3
    max_experiments_per_iteration: int = 4
    primary_metric: str = "auc"
    auto_approve_plan: bool = False
    report_style: str = "academic"    # academic | summary | comparison
    gateway_url: str = "http://127.0.0.1:6100"
    auth_token: str = ""
