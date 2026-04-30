"""CLI rendering helpers — status line, formatting."""
from __future__ import annotations


DIM = "\033[2m"
RESET = "\033[0m"


def build_status_line(state, model_name: str, sandbox_mode: str) -> str:
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
        f"iter:{iter_str} | conv:{short_conv}{synth}{RESET}"
    )
