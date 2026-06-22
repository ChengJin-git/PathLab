"""LLM-facing summary for the PathScientist execution console."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any

from ..config import PathScientistConfig
from .types import ResearchSessionState

logger = logging.getLogger(__name__)

DEFAULT_UI_SUMMARY_MODEL = "gpt-5.5"
UI_RUN_SUMMARY_KEYS = ("user_request", "agent_actions", "result", "brief")


def _compact_text(value: Any, *, max_chars: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _metric_label(state: ResearchSessionState) -> str:
    metric_name = (state.objective.success_metric or "metric").upper()
    value = float(state.best_metric_value or 0.0)
    if value <= 0:
        return ""
    formatted = f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}"
    suffix = f" in {state.best_run_id}" if state.best_run_id else ""
    return f"{metric_name} {formatted}{suffix}"


def _json_safe_run_history(state: ResearchSessionState) -> list[dict[str, Any]]:
    return [asdict(record) for record in state.run_history[-8:]]


def build_fallback_ui_run_summary(state: ResearchSessionState) -> dict[str, str]:
    """Build a deterministic UI summary when the LLM is unavailable."""
    iterations = len(state.run_history)
    committed = sum(1 for record in state.run_history if record.committed)
    metric = _metric_label(state)
    question = _compact_text(state.objective.question, max_chars=600)
    stage = state.stage or "unknown"

    if iterations:
        actions = (
            f"The agent ran {iterations} iteration{'s' if iterations != 1 else ''}, "
            f"with {committed} committed result{'s' if committed != 1 else ''}, "
            "and tracked experiment metrics for review."
        )
    else:
        actions = (
            "The agent prepared the run context, but no finalized experiment "
            "iterations were recorded."
        )

    if metric:
        result = f"The best detected result was {metric}."
    elif state.stop_reason:
        result = f"The run stopped at stage {stage} with reason: {state.stop_reason}."
    else:
        result = f"The run reached stage {stage}, but no best metric was recorded."

    return {
        "user_request": question or "No user request was captured for this run.",
        "agent_actions": actions,
        "result": result,
        "brief": _compact_text(state.final_summary, max_chars=240) or result,
        "model": "fallback",
    }


def parse_ui_run_summary_response(text: str) -> dict[str, str]:
    """Extract the first JSON object and keep the UI summary fields."""
    raw = str(text or "").strip()
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    if not isinstance(payload, dict):
        return {}

    summary: dict[str, str] = {}
    for key in UI_RUN_SUMMARY_KEYS:
        value = _compact_text(payload.get(key), max_chars=1200)
        if value:
            summary[key] = value
    return summary


def _build_prompt(state: ResearchSessionState) -> str:
    context = {
        "user_request": state.objective.question,
        "stage": state.stage,
        "stop_reason": state.stop_reason,
        "success_metric": state.objective.success_metric,
        "best_run_id": state.best_run_id,
        "best_metric_value": state.best_metric_value,
        "iterations": _json_safe_run_history(state),
        "stage_history": state.stage_history,
        "task_profile": state.task_profile,
        "selected_dataset": state.selected_dataset,
        "final_summary": state.final_summary,
    }
    return (
        "You are writing a concise UI run summary for a computational pathology "
        "research agent. Summarize the whole run, not the latest log line.\n"
        "Return ONLY valid JSON with these string keys: user_request, "
        "agent_actions, result, brief.\n"
        "- user_request: what the user asked for.\n"
        "- agent_actions: what the agent actually did during the run.\n"
        "- result: the outcome, including best metric or stop/failure reason.\n"
        "- brief: one sentence overview for a card header.\n"
        "Keep each value under 80 words. Do not include markdown.\n\n"
        f"Run context:\n{json.dumps(context, ensure_ascii=False, default=str)}"
    )


def build_ui_run_summary(
    state: ResearchSessionState,
    config: PathScientistConfig | None = None,
) -> dict[str, str]:
    """Generate the persisted UI summary, falling back deterministically."""
    fallback = build_fallback_ui_run_summary(state)
    try:
        from openhands.sdk.llm import Message, TextContent
        from ..llm_client import (
            build_chat_llm,
            extract_text,
            invoke_chat_llm,
            make_llm_config,
        )

        model = getattr(config, "llm_model", "") or DEFAULT_UI_SUMMARY_MODEL
        llm_config = make_llm_config(config=config, llm_model=model)
        llm = build_chat_llm(
            llm_config,
            component="PathScientist UI run summary",
            usage_id="pathscientist_ui_run_summary",
            temperature=0.0,
        )
        response = invoke_chat_llm(
            llm,
            messages=[Message(role="user", content=[TextContent(text=_build_prompt(state))])],
        )
        parsed = parse_ui_run_summary_response(extract_text(response))
        if not parsed:
            return fallback
        return {
            "user_request": parsed.get("user_request") or fallback["user_request"],
            "agent_actions": parsed.get("agent_actions") or fallback["agent_actions"],
            "result": parsed.get("result") or fallback["result"],
            "brief": parsed.get("brief") or fallback["brief"],
            "model": model,
        }
    except Exception as exc:
        logger.debug("PathScientist UI run summary fallback: %s", exc)
        return fallback
