"""CLI rendering helpers — status line, formatting."""
from __future__ import annotations

import time


DIM = "\033[2m"
RESET = "\033[0m"


def format_duration(seconds: float | int | None) -> str:
    """Format wall-clock seconds for compact CLI display."""
    if seconds is None:
        return "-"
    try:
        total = int(max(0, float(seconds)))
    except (TypeError, ValueError):
        return "-"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def format_last_turn(seconds: float | int | None) -> str:
    if not seconds:
        return "-"
    value = max(0.0, float(seconds))
    if value < 60:
        return f"{value:.1f}s"
    return format_duration(value)


def build_status_line(state, model_name: str, sandbox_mode: str, now_monotonic: float | None = None) -> str:
    """Build a one-line status string for display before the prompt."""
    stage = getattr(getattr(state, "research_state", None), "stage", "idle")
    max_iterations = getattr(getattr(state, "research_state", None), "max_iterations", 0)
    best_value = getattr(getattr(state, "tracker", None), "best_value", 0.0)
    iteration = getattr(getattr(state, "tracker", None), "iteration", 0)
    metric = getattr(getattr(state, "tracker", None), "primary_metric", "auc")
    conv_id = getattr(getattr(state, "session", None), "conversation_id", "")
    short_conv = str(conv_id)[:8] if conv_id else "-"

    iter_str = f"{iteration}/{max_iterations}" if max_iterations else str(iteration)

    # Shorten model name for display
    short_model = model_name.split("/")[-1][:20] if model_name else "-"

    started = float(getattr(state, "session_started_monotonic", 0.0) or 0.0)
    elapsed = "-"
    if started:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        elapsed = format_duration(now - started)
    last_turn = format_last_turn(getattr(state, "last_turn_seconds", 0.0))

    # Synthesis hints
    rs = getattr(state, "research_state", None)
    has_report = bool(getattr(rs, "report_markdown_path", ""))
    claim_count = getattr(rs, "claim_count", 0) or 0
    synth = ""
    if has_report:
        synth = f" | report:yes claims:{claim_count}"

    return (
        f"{DIM}{state.mode} | {short_model} | "
        f"stage:{stage} | {metric}:{best_value:.4f} | "
        f"iter:{iter_str} | elapsed:{elapsed} | last:{last_turn} | "
        f"conv:{short_conv}{synth}{RESET}"
    )
