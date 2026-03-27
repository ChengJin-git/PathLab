"""
Auto Research Agent — Graph Nodes

9 nodes implementing the full research pipeline:
coordinator → literature_review → experiment_planner → human_review →
experiment_executor → experiment_monitor → results_analyzer →
iteration_router → reporter
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import Command, interrupt

from .knowhow import retrieve_knowhow
from .prompts import (
    COORDINATOR_PROMPT,
    EXPERIMENT_PLANNER_PROMPT,
    HUMAN_REVIEW_PROMPT,
    ITERATION_CONTEXT_TEMPLATE,
    ITERATION_ROUTER_PROMPT,
    LITERATURE_REVIEW_PROMPT,
    REPORTER_PROMPT,
)
from .tools import (
    ANALYZER_TOOLS,
    EXECUTOR_TOOLS,
    MONITOR_TOOLS,
    PLANNER_TOOLS,
    configure_tools,
)
from .types import (
    AutoResearchState,
    PHASE_ANALYZING,
    PHASE_EXECUTING,
    PHASE_LITERATURE,
    PHASE_MONITORING,
    PHASE_PLANNING,
    PHASE_REPORTING,
    PHASE_REVIEW,
    PHASE_ROUTING,
)

logger = logging.getLogger(__name__)


# =============================================================================
# LLM Helper
# =============================================================================

def _get_llm(temperature: float = 0.0, bind_tools: list | None = None) -> ChatOpenAI:
    """Get a ChatOpenAI instance from PathLab global settings or env vars."""
    # Try PathLab global settings first (local vLLM or OpenRouter)
    base_url = None
    model = None
    api_key = "not-needed"

    try:
        from backend.common.config import Config
        settings = Config.get_global_settings()

        if settings.get("local_vllm_enabled") and settings.get("local_vllm_base_url"):
            base_url = settings["local_vllm_base_url"]
            model = settings.get("local_vllm_model") or None
            api_key = settings.get("local_vllm_api_key") or "not-needed"
        elif settings.get("openrouter_api_key"):
            base_url = settings.get("openrouter_base_url", "https://openrouter.ai/api/v1")
            model = settings.get("openrouter_model", "qwen/qwen3.5-plus-02-15")
            api_key = settings["openrouter_api_key"]
    except Exception:
        pass

    # Fallback to env vars
    if not base_url:
        base_url = os.getenv("LLM_BASE_URL", os.getenv("VLLM_URL", "http://127.0.0.1:8000/v1"))
    if not model:
        model = os.getenv("LLM_MODEL", os.getenv("VLLM_MODEL", None))
    if api_key == "not-needed":
        api_key = os.getenv("LLM_API_KEY", os.getenv("VLLM_KEY", "not-needed"))

    if not model:
        # Last resort: try to detect from vLLM /models endpoint
        try:
            import httpx
            headers = {}
            if api_key and api_key != "not-needed":
                headers["Authorization"] = f"Bearer {api_key}"
            resp = httpx.get(f"{base_url}/models", headers=headers, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data"):
                    model = data["data"][0].get("id")
        except Exception:
            pass

    if not model:
        model = "default"

    llm = ChatOpenAI(
        base_url=base_url,
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=4096,
    )

    if bind_tools:
        llm = llm.bind_tools(bind_tools)

    return llm


def _parse_json_from_response(content: str) -> Any:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = content.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try json-repair if available
        try:
            from json_repair import repair_json
            return json.loads(repair_json(text))
        except Exception:
            return None


def _is_stop_requested(state: AutoResearchState) -> bool:
    return state.get("stop_requested", False)


# =============================================================================
# Node 1: Coordinator
# =============================================================================

def coordinator_node(
    state: AutoResearchState,
) -> Command[Literal["literature_review", "__end__"]]:
    """
    Parse research question, detect locale, check feasibility.
    Routes to literature_review or END.
    """
    if _is_stop_requested(state):
        return Command(
            update={"phase": PHASE_REPORTING, "final_report": "Research stopped by user."},
            goto="reporter",
        )

    research_question = state.get("research_question", "")
    logger.info(f"[coordinator] Research question: {research_question}")

    llm = _get_llm(temperature=0.0)
    messages = [
        SystemMessage(content=COORDINATOR_PROMPT),
        HumanMessage(content=f"Research question: {research_question}"),
    ]
    response = llm.invoke(messages)
    parsed = _parse_json_from_response(response.content)

    locale = "en-US"
    if parsed and isinstance(parsed, dict):
        locale = parsed.get("locale", "en-US")
        feasible = parsed.get("feasible", True)
        if not feasible:
            reason = parsed.get("reason", "Not feasible")
            return Command(
                update={
                    "locale": locale,
                    "phase": PHASE_REPORTING,
                    "final_report": f"# Research Not Feasible\n\n{reason}",
                    "messages": [AIMessage(content=f"Research not feasible: {reason}")],
                },
                goto="reporter",
            )

    return Command(
        update={
            "locale": locale,
            "phase": PHASE_LITERATURE,
            "messages": [AIMessage(content=f"Starting literature review for: {research_question}")],
        },
        goto="literature_review",
    )


# =============================================================================
# Node 2: Literature Review
# =============================================================================

async def literature_review_node(
    state: AutoResearchState,
) -> Command[Literal["experiment_planner"]]:
    """
    Search literature for relevant methods, extract extractors/aggregators/metrics.
    Uses search tools (Tavily/Exa).
    """
    if _is_stop_requested(state):
        return Command(update={"phase": PHASE_REPORTING}, goto="reporter")

    research_question = state.get("research_question", "")
    logger.info(f"[literature_review] Searching for: {research_question}")

    prompt = LITERATURE_REVIEW_PROMPT.format(research_question=research_question)

    # Use LLM with search tool binding
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        search_tool = TavilySearchResults(max_results=5)
        llm = _get_llm(temperature=0.0, bind_tools=[search_tool])
    except Exception:
        # Fallback without search tools
        llm = _get_llm(temperature=0.0)

    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=f"Find the best methods for: {research_question}"),
    ]

    # Multi-turn: let LLM call search tools iteratively
    max_tool_rounds = 3
    for _ in range(max_tool_rounds):
        response = await llm.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        # Execute tool calls
        for tool_call in response.tool_calls:
            try:
                if tool_call["name"] == "tavily_search_results_json":
                    result = await search_tool.ainvoke(tool_call["args"])
                else:
                    result = f"Unknown tool: {tool_call['name']}"
            except Exception as e:
                result = f"Search error: {e}"

            from langchain_core.messages import ToolMessage
            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            ))

    # Parse findings from final response
    findings = _parse_json_from_response(response.content)
    if not isinstance(findings, list):
        findings = []

    logger.info(f"[literature_review] Found {len(findings)} relevant papers")

    return Command(
        update={
            "phase": PHASE_PLANNING,
            "literature_findings": findings,
            "messages": [AIMessage(
                content=f"Literature review complete. Found {len(findings)} relevant papers.\n\n"
                        + "\n".join(f"- {f.get('title', 'Untitled')}" for f in findings[:5])
            )],
        },
        goto="experiment_planner",
    )


# =============================================================================
# Node 3: Experiment Planner
# =============================================================================

async def experiment_planner_node(
    state: AutoResearchState,
) -> Command[Literal["human_review"]]:
    """
    Design experiments based on literature + available resources + know-how.
    Queries PathLab API for available datasets/extractors/aggregators.
    """
    if _is_stop_requested(state):
        return Command(update={"phase": PHASE_REPORTING}, goto="reporter")

    research_question = state.get("research_question", "")
    literature_findings = state.get("literature_findings", [])
    iteration = state.get("iteration", 0)
    comparison_table = state.get("comparison_table", {})
    best_experiment = state.get("best_experiment", {})
    best_metric = state.get("best_metric", 0.0)
    best_metric_name = state.get("best_metric_name", "auc")
    improvement_history = state.get("improvement_history", [])
    max_experiments = 4

    logger.info(f"[experiment_planner] Iteration {iteration}, designing experiments")

    # 1. Query available resources via tools
    llm_with_tools = _get_llm(temperature=0.0, bind_tools=PLANNER_TOOLS)
    resource_messages = [
        SystemMessage(content="Query PathLab for available resources. Call list_pathlab_datasets, get_training_options, and get_gpu_info."),
        HumanMessage(content="What datasets, extractors, and GPU resources are available?"),
    ]

    available_resources = {}
    max_tool_rounds = 3
    for _ in range(max_tool_rounds):
        response = await llm_with_tools.ainvoke(resource_messages)
        resource_messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            matching_tools = [t for t in PLANNER_TOOLS if t.name == tool_name]
            if matching_tools:
                try:
                    result = await matching_tools[0].ainvoke(tool_call["args"])
                    parsed = json.loads(result) if isinstance(result, str) else result
                    if parsed.get("status") == "success":
                        available_resources[tool_name] = parsed.get("data", {})
                except Exception as e:
                    result = f"Error: {e}"

                from langchain_core.messages import ToolMessage
                resource_messages.append(ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call["id"],
                ))

    # 2. Get know-how recommendations
    knowhow = retrieve_knowhow(research_question)

    # 3. Build iteration context if not first round
    iteration_context = ""
    if iteration > 0 and comparison_table:
        iteration_context = ITERATION_CONTEXT_TEMPLATE.format(
            iteration=iteration,
            max_iterations=state.get("max_iterations", 3),
            best_experiment_name=best_experiment.get("name", "N/A"),
            best_metric_name=best_metric_name,
            best_metric_value=best_metric,
            comparison_table=json.dumps(comparison_table, indent=2, ensure_ascii=False),
            improvement_history=json.dumps(improvement_history, indent=2, ensure_ascii=False),
        )

    # 4. Ask LLM to design experiments
    prompt = EXPERIMENT_PLANNER_PROMPT.format(
        research_question=research_question,
        available_resources=json.dumps(available_resources, indent=2, ensure_ascii=False, default=str),
        knowhow=json.dumps(knowhow, indent=2, ensure_ascii=False),
        literature_findings=json.dumps(literature_findings[:5], indent=2, ensure_ascii=False),
        iteration_context=iteration_context,
        max_experiments=max_experiments,
    )

    planner_llm = _get_llm(temperature=0.1)
    plan_response = await planner_llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"Design experiments for: {research_question}"),
    ])

    experiment_plan = _parse_json_from_response(plan_response.content)
    if not isinstance(experiment_plan, list):
        experiment_plan = []

    logger.info(f"[experiment_planner] Designed {len(experiment_plan)} experiments")

    return Command(
        update={
            "phase": PHASE_REVIEW,
            "available_resources": available_resources,
            "experiment_plan": experiment_plan,
            "plan_approved": False,
            "messages": [AIMessage(content=plan_response.content)],
        },
        goto="human_review",
    )


# =============================================================================
# Node 4: Human Review
# =============================================================================

def human_review_node(
    state: AutoResearchState,
) -> Command[Literal["experiment_executor", "experiment_planner"]]:
    """
    Present experiment plan to user for approval.
    Uses interrupt() to pause graph until user responds.
    """
    if _is_stop_requested(state):
        return Command(update={"phase": PHASE_REPORTING}, goto="reporter")

    experiment_plan = state.get("experiment_plan", [])
    auto_approve = state.get("auto_approve_plan", False)

    if auto_approve:
        logger.info("[human_review] Auto-approved")
        return Command(
            update={"plan_approved": True, "phase": PHASE_EXECUTING},
            goto="experiment_executor",
        )

    # Interrupt and wait for user feedback
    plan_summary = json.dumps(experiment_plan, indent=2, ensure_ascii=False)
    feedback = interrupt(f"Please review the experiment plan:\n\n{plan_summary}")

    if not feedback:
        return Command(
            update={"phase": PHASE_PLANNING},
            goto="experiment_planner",
        )

    feedback_str = str(feedback).strip().upper()

    if feedback_str.startswith("[ACCEPTED]") or feedback_str == "ACCEPTED":
        logger.info("[human_review] Plan accepted by user")
        return Command(
            update={"plan_approved": True, "phase": PHASE_EXECUTING},
            goto="experiment_executor",
        )

    if feedback_str.startswith("[EDIT_PLAN]"):
        edit_instructions = str(feedback)[len("[EDIT_PLAN]"):].strip()
        logger.info(f"[human_review] Plan edit requested: {edit_instructions}")
        return Command(
            update={
                "phase": PHASE_PLANNING,
                "messages": [HumanMessage(content=f"Please modify the plan: {edit_instructions}")],
            },
            goto="experiment_planner",
        )

    # Default: treat as edit request
    logger.info(f"[human_review] Treating feedback as edit: {feedback}")
    return Command(
        update={
            "phase": PHASE_PLANNING,
            "messages": [HumanMessage(content=f"User feedback: {feedback}")],
        },
        goto="experiment_planner",
    )


# =============================================================================
# Node 5: Experiment Executor
# =============================================================================

async def experiment_executor_node(
    state: AutoResearchState,
) -> Command[Literal["experiment_monitor"]]:
    """
    Submit training tasks to PathLab API for each experiment in the plan.
    """
    if _is_stop_requested(state):
        return Command(update={"phase": PHASE_REPORTING}, goto="reporter")

    experiment_plan = state.get("experiment_plan", [])
    logger.info(f"[experiment_executor] Submitting {len(experiment_plan)} experiments")

    submitted_tasks: dict[str, dict] = {}

    for exp in experiment_plan:
        exp_id = exp.get("id", f"exp_{len(submitted_tasks)}")

        try:
            submit_tool = EXECUTOR_TOOLS[0]  # SubmitTrainingTaskTool
            result_str = await submit_tool.ainvoke({
                "task_name": exp.get("name", f"AutoResearch_{exp_id}"),
                "task_type": exp.get("task_type", "classification"),
                "dataset_id": exp.get("dataset_id", ""),
                "feature_extractor": exp.get("feature_extractor", "UNI2"),
                "aggregator": exp.get("aggregator", "abmil"),
                "learning_rate": exp.get("hyperparams", {}).get("learning_rate", 0.0001),
                "epochs": exp.get("hyperparams", {}).get("epochs", 50),
                "optimizer": exp.get("hyperparams", {}).get("optimizer", "adamw"),
                "batch_size": exp.get("hyperparams", {}).get("batch_size", 16),
                "split_strategy": exp.get("split_config", {}).get("strategy", "random"),
                "split_ratios": exp.get("split_config", {}).get("ratios", {"train": 0.7, "val": 0.1, "test": 0.2}),
                "seed": exp.get("split_config", {}).get("seed", 42),
            })

            result = json.loads(result_str) if isinstance(result_str, str) else result_str
            if result.get("status") == "success":
                task_id = result["data"]["task_id"]
                submitted_tasks[exp_id] = {
                    "training_task_id": task_id,
                    "config": exp,
                    "status": "submitted",
                }
                logger.info(f"[experiment_executor] {exp_id} → task {task_id}")
            else:
                submitted_tasks[exp_id] = {
                    "training_task_id": None,
                    "config": exp,
                    "status": "failed_to_submit",
                    "error": result.get("data", {}).get("error", "Unknown error"),
                }

        except Exception as e:
            logger.error(f"[experiment_executor] Failed to submit {exp_id}: {e}")
            submitted_tasks[exp_id] = {
                "training_task_id": None,
                "config": exp,
                "status": "failed_to_submit",
                "error": str(e),
            }

    submitted_count = sum(1 for t in submitted_tasks.values() if t["status"] == "submitted")
    logger.info(f"[experiment_executor] {submitted_count}/{len(experiment_plan)} experiments submitted")

    return Command(
        update={
            "phase": PHASE_MONITORING,
            "submitted_tasks": submitted_tasks,
            "messages": [AIMessage(
                content=f"Submitted {submitted_count}/{len(experiment_plan)} training tasks. Waiting for completion..."
            )],
        },
        goto="experiment_monitor",
    )


# =============================================================================
# Node 6: Experiment Monitor
# =============================================================================

def experiment_monitor_node(
    state: AutoResearchState,
) -> Command[Literal["results_analyzer"]]:
    """
    Interrupt and wait for external ExperimentMonitor to resume when training completes.
    The monitor polls GET /tasks/training/{task_id} and resumes with results.
    """
    submitted_tasks = state.get("submitted_tasks", {})
    active_task_ids = [
        t["training_task_id"]
        for t in submitted_tasks.values()
        if t.get("training_task_id") and t["status"] == "submitted"
    ]

    if not active_task_ids:
        logger.info("[experiment_monitor] No active tasks, skipping to analyzer")
        return Command(
            update={"phase": PHASE_ANALYZING},
            goto="results_analyzer",
        )

    logger.info(f"[experiment_monitor] Waiting for {len(active_task_ids)} tasks: {active_task_ids}")

    # Interrupt — external monitor will resume with completed/failed results
    resume_data = interrupt(
        f"Waiting for {len(active_task_ids)} training task(s) to complete: {active_task_ids}"
    )

    # Parse resume data (provided by ExperimentMonitor)
    completed = []
    failed = []

    if resume_data:
        try:
            data = json.loads(resume_data) if isinstance(resume_data, str) else resume_data
            completed = data.get("completed", [])
            failed = data.get("failed", [])
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"[experiment_monitor] Could not parse resume data: {resume_data}")

    logger.info(f"[experiment_monitor] Resumed: {len(completed)} completed, {len(failed)} failed")

    return Command(
        update={
            "phase": PHASE_ANALYZING,
            "completed_results": completed,
            "failed_results": failed,
            "messages": [AIMessage(
                content=f"Training complete: {len(completed)} succeeded, {len(failed)} failed."
            )],
        },
        goto="results_analyzer",
    )


# =============================================================================
# Node 7: Results Analyzer
# =============================================================================

async def results_analyzer_node(
    state: AutoResearchState,
) -> Command[Literal["iteration_router"]]:
    """
    Run analysis on completed experiments, build comparison table,
    update ratchet baseline.
    """
    if _is_stop_requested(state):
        return Command(update={"phase": PHASE_REPORTING}, goto="reporter")

    completed_results = state.get("completed_results", [])
    best_metric = state.get("best_metric", 0.0)
    best_metric_name = state.get("best_metric_name", "auc")
    best_experiment = state.get("best_experiment", {})
    iteration = state.get("iteration", 0)

    logger.info(f"[results_analyzer] Analyzing {len(completed_results)} completed experiments")

    # Run analysis for each completed experiment
    analyzed_results = []
    for result in completed_results:
        task_id = result.get("training_task_id")
        if not task_id:
            continue

        try:
            # Run analysis
            run_tool = ANALYZER_TOOLS[0]  # RunAnalysisTool
            await run_tool.ainvoke({"task_id": task_id})

            # Get results
            get_tool = ANALYZER_TOOLS[1]  # GetAnalysisResultsTool
            result_str = await get_tool.ainvoke({"task_id": task_id})
            parsed = json.loads(result_str) if isinstance(result_str, str) else result_str

            if parsed.get("status") == "success":
                metrics = parsed.get("data", {}).get("metrics", {})
                result["metrics"] = metrics
                analyzed_results.append(result)
        except Exception as e:
            logger.error(f"[results_analyzer] Failed to analyze task {task_id}: {e}")

    # Build comparison table
    columns = ["experiment_id", "extractor", "aggregator", best_metric_name, "accuracy", "f1"]
    rows = []
    for r in analyzed_results:
        metrics = r.get("metrics", {})
        rows.append({
            "experiment_id": r.get("experiment_id", ""),
            "extractor": r.get("config", {}).get("feature_extractor", ""),
            "aggregator": r.get("config", {}).get("aggregator", ""),
            best_metric_name: metrics.get(best_metric_name, 0.0),
            "accuracy": metrics.get("accuracy", 0.0),
            "f1": metrics.get("f1", 0.0),
        })

    # Sort by primary metric
    rows.sort(key=lambda r: r.get(best_metric_name, 0.0), reverse=True)

    comparison_table = {"columns": columns, "rows": rows}

    # Update ratchet: check if any experiment beat the best
    improvement_entries = []
    new_best_metric = best_metric
    new_best_experiment = best_experiment

    for row in rows:
        metric_val = row.get(best_metric_name, 0.0)
        improved = metric_val > new_best_metric
        if improved:
            new_best_metric = metric_val
            new_best_experiment = row

        improvement_entries.append({
            "iteration": iteration,
            "experiment_id": row.get("experiment_id", ""),
            "metric_value": metric_val,
            "improved": improved,
        })

    analysis_summary = ""
    if rows:
        best_row = rows[0]
        analysis_summary = (
            f"Best experiment: {best_row.get('extractor')}+{best_row.get('aggregator')} "
            f"with {best_metric_name}={best_row.get(best_metric_name, 0):.4f}"
        )

    logger.info(f"[results_analyzer] Best {best_metric_name}: {new_best_metric:.4f}")

    return Command(
        update={
            "phase": PHASE_ROUTING,
            "comparison_table": comparison_table,
            "analysis_summary": analysis_summary,
            "best_metric": new_best_metric,
            "best_experiment": new_best_experiment,
            "improvement_history": improvement_entries,
            "messages": [AIMessage(content=f"Analysis complete. {analysis_summary}")],
        },
        goto="iteration_router",
    )


# =============================================================================
# Node 8: Iteration Router
# =============================================================================

async def iteration_router_node(
    state: AutoResearchState,
) -> Command[Literal["experiment_planner", "reporter"]]:
    """
    Decide whether to iterate (try more experiments) or generate final report.
    """
    if _is_stop_requested(state):
        return Command(update={"phase": PHASE_REPORTING}, goto="reporter")

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)
    comparison_table = state.get("comparison_table", {})
    best_experiment = state.get("best_experiment", {})
    best_metric = state.get("best_metric", 0.0)
    best_metric_name = state.get("best_metric_name", "auc")
    improvement_history = state.get("improvement_history", [])

    # Hard stop: max iterations reached
    if iteration >= max_iterations:
        logger.info(f"[iteration_router] Max iterations ({max_iterations}) reached → reporter")
        return Command(
            update={
                "phase": PHASE_REPORTING,
                "messages": [AIMessage(content=f"Max iterations reached ({max_iterations}). Generating report.")],
            },
            goto="reporter",
        )

    # Ask LLM to decide
    prompt = ITERATION_ROUTER_PROMPT.format(
        research_question=state.get("research_question", ""),
        comparison_table=json.dumps(comparison_table, indent=2, ensure_ascii=False),
        best_experiment=json.dumps(best_experiment, indent=2, ensure_ascii=False),
        best_metric=best_metric,
        best_metric_name=best_metric_name,
        iteration=iteration,
        max_iterations=max_iterations,
        improvement_history=json.dumps(improvement_history, indent=2, ensure_ascii=False),
    )

    llm = _get_llm(temperature=0.0)
    response = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content="Should we continue iterating or stop?"),
    ])

    decision = _parse_json_from_response(response.content)

    if decision and isinstance(decision, dict):
        action = decision.get("decision", "STOP").upper()
        reason = decision.get("reason", "")
    else:
        action = "STOP"
        reason = "Could not parse decision"

    if action == "CONTINUE":
        logger.info(f"[iteration_router] Continuing to iteration {iteration + 1}: {reason}")
        return Command(
            update={
                "phase": PHASE_PLANNING,
                "iteration": iteration + 1,
                "messages": [AIMessage(content=f"Iteration {iteration + 1}: {reason}")],
            },
            goto="experiment_planner",
        )

    logger.info(f"[iteration_router] Stopping: {reason}")
    return Command(
        update={
            "phase": PHASE_REPORTING,
            "messages": [AIMessage(content=f"Stopping iteration: {reason}")],
        },
        goto="reporter",
    )


# =============================================================================
# Node 9: Reporter
# =============================================================================

async def reporter_node(
    state: AutoResearchState,
) -> Command[Literal["__end__"]]:
    """
    Generate final research report based on all accumulated findings.
    """
    research_question = state.get("research_question", "")
    literature_findings = state.get("literature_findings", [])
    comparison_table = state.get("comparison_table", {})
    best_experiment = state.get("best_experiment", {})
    best_metric = state.get("best_metric", 0.0)
    best_metric_name = state.get("best_metric_name", "auc")
    improvement_history = state.get("improvement_history", [])
    analysis_summary = state.get("analysis_summary", "")

    # If we already have a final report (e.g., from early termination), use it
    existing_report = state.get("final_report", "")
    if existing_report and existing_report != "Research stopped by user.":
        return Command(
            update={"phase": PHASE_REPORTING},
            goto="__end__",
        )

    logger.info("[reporter] Generating final report")

    prompt = REPORTER_PROMPT.format(
        report_style="academic",
        research_question=research_question,
        literature_findings=json.dumps(literature_findings[:5], indent=2, ensure_ascii=False),
        comparison_table=json.dumps(comparison_table, indent=2, ensure_ascii=False),
        best_experiment=json.dumps(best_experiment, indent=2, ensure_ascii=False),
        best_metric=best_metric,
        best_metric_name=best_metric_name,
        improvement_history=json.dumps(improvement_history, indent=2, ensure_ascii=False),
        analysis_summary=analysis_summary,
    )

    llm = _get_llm(temperature=0.2)
    response = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content="Generate the final research report."),
    ])

    final_report = response.content
    logger.info(f"[reporter] Report generated ({len(final_report)} chars)")

    return Command(
        update={
            "phase": PHASE_REPORTING,
            "final_report": final_report,
            "messages": [AIMessage(content=final_report)],
        },
        goto="__end__",
    )
