"""CLI slash command dispatcher."""
from __future__ import annotations

from dataclasses import dataclass
import time

from .cli_render import format_duration
from .cli_progress import (
    format_download_progress_status,
    load_download_progress_for_state,
)


@dataclass
class CommandResult:
    handled: bool
    output: str = ""
    should_exit: bool = False


def handle_command(text: str, state, now_monotonic: float | None = None) -> CommandResult:
    """Dispatch a slash command. Returns CommandResult with handled=False if not a command."""
    if not text.startswith("/"):
        return CommandResult(handled=False)

    parts = text.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit", "/q"):
        return CommandResult(handled=True, should_exit=True)

    if cmd == "/help":
        return CommandResult(handled=True, output=_help_text())

    if cmd == "/status":
        return _cmd_status(state, now_monotonic=now_monotonic)

    if cmd == "/mode":
        return _cmd_mode(arg, state)

    if cmd == "/metrics":
        return _cmd_metrics(state)

    if cmd == "/workspace":
        return _cmd_workspace(state)

    if cmd == "/summary":
        return _cmd_summary(state)

    if cmd == "/details":
        state.details = not state.details
        return CommandResult(handled=True, output=f"Details {'on' if state.details else 'off'}")

    if cmd == "/report":
        return _cmd_report(state)

    if cmd == "/new":
        return _cmd_new(state)

    if cmd == "/sessions":
        return _cmd_sessions(state)

    if cmd == "/search":
        if not arg:
            return CommandResult(True, "Usage: /search <query>  (e.g. /search TransMIL pathology)")
        return CommandResult(handled=True, output=f"__search__:{arg}")

    if cmd == "/resume":
        # Handled by caller (needs config), just signal intent
        return CommandResult(handled=True, output=f"__resume__:{arg}")

    if cmd == "/approve":
        return _cmd_approve(state)

    if cmd == "/reject":
        return _cmd_reject(state)

    return CommandResult(handled=True, output=f"Unknown command: {cmd}. Type /help for available commands.")


def _help_text() -> str:
    return """Available commands:
  /status     — session stage, metrics, iteration
  /mode <m>   — switch mode (research|code) before session starts
  /metrics    — show current metrics and history
  /workspace  — show workspace files and git log
  /summary    — show research session summary
  /report     — show generated report and paper draft paths
  /details    — toggle verbose output
  /new        — end current session, start fresh
  /sessions   — list saved conversations
  /search <q>  — search online for papers (OpenAlex)
  /resume <id> — resume a saved conversation
  /approve    — approve the grounding plan and continue to execution
  /reject     — reject the grounding plan and terminate
  /quit       — exit"""


def _cmd_status(state, now_monotonic: float | None = None) -> CommandResult:
    if not state.ready:
        return CommandResult(True, "No active session. Type a research goal to start.")
    lines = [f"Mode: {state.mode}"]
    rs = getattr(state, "research_state", None)
    stage = getattr(rs, "stage", None)
    if stage:
        lines.append(f"Stage: {stage}")
    started = float(getattr(state, "session_started_monotonic", 0.0) or 0.0)
    if started:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        lines.append(f"Elapsed: {format_duration(now - started)}")
    last_turn = float(getattr(state, "last_turn_seconds", 0.0) or 0.0)
    if last_turn:
        lines.append(f"Last turn: {format_duration(last_turn)}")
    if state.tracker:
        lines.append(f"Best {state.tracker.primary_metric}: {state.tracker.best_value:.4f}")
        lines.append(f"Iterations: {state.tracker.iteration}")
    if state.session:
        lines.append(f"Conversation: {state.session.conversation_id}")
    download = format_download_progress_status(load_download_progress_for_state(state))
    if download:
        lines.append(download)
    # Surface IntegrityGuard outcome when present. Fatal issues indicate a
    # broken pipeline (empty git log, blank run_id, missing evidence, ...)
    # and must be rendered here so users see the problem at a glance rather
    # than discovering it silently in a paper draft.
    integrity = getattr(rs, "integrity_report", None) or {}
    if integrity:
        fatal = int(integrity.get("fatal_count", 0) or 0)
        warning = int(integrity.get("warning_count", 0) or 0)
        lines.append(f"Integrity: fatal={fatal}, warning={warning}")
        for issue in integrity.get("issues", []) or []:
            code = issue.get("code", "?")
            severity = issue.get("severity", "?")
            message = issue.get("message", "")
            lines.append(f"  [{severity}] {code}: {message}")
    return CommandResult(True, "\n".join(lines))


def _cmd_mode(arg: str, state) -> CommandResult:
    if not arg or arg not in ("research", "code"):
        return CommandResult(True, f"Current mode: {state.mode}. Usage: /mode research|code")
    if state.ready:
        return CommandResult(True, "Session already active. Use /new before switching mode.")
    state.mode = arg
    return CommandResult(True, f"Mode set to {arg}")


def _cmd_metrics(state) -> CommandResult:
    if not state.tracker:
        return CommandResult(True, "No metrics yet.")
    lines = [f"Primary: {state.tracker.primary_metric}"]
    lines.append(f"Best: {state.tracker.best_value:.4f}")
    lines.append(f"Iterations: {state.tracker.iteration}")
    if state.tracker.history:
        lines.append("History:")
        for h in state.tracker.history[-5:]:
            lines.append(f"  {h}")
    return CommandResult(True, "\n".join(lines))


def _cmd_workspace(state) -> CommandResult:
    if not state.workspace:
        return CommandResult(True, "No workspace yet.")
    lines = [f"Root: {state.workspace.root}"]
    lines.append(f"Files: {state.workspace.list_files()}")
    history = state.workspace.get_history()
    if history:
        lines.append(f"Commits: {len(history)}")
        for h in history[:5]:
            lines.append(f"  {h}")
    return CommandResult(True, "\n".join(lines))


def _cmd_summary(state) -> CommandResult:
    summary = getattr(getattr(state, "research_state", None), "final_summary", "")
    if summary:
        return CommandResult(True, summary)
    return CommandResult(True, "No research summary yet.")


def _cmd_report(state) -> CommandResult:
    rs = getattr(state, "research_state", None)
    if not rs:
        return CommandResult(True, "No research session. Start one first.")
    lines = []
    md_path = getattr(rs, "report_markdown_path", "") or ""
    draft_path = getattr(rs, "paper_draft_path", "") or ""
    claim_count = getattr(rs, "claim_count", 0) or 0
    if md_path:
        lines.append(f"Report:      {md_path}")
    if draft_path:
        lines.append(f"Paper draft: {draft_path}")
    if claim_count:
        lines.append(f"Claims:      {claim_count}")
    verification_passed = getattr(rs, "paper_verification_passed", None)
    verification_issues = getattr(rs, "paper_verification_issue_count", 0)
    if verification_passed is not None:
        status = "PASSED" if verification_passed else "FAILED"
        if verification_issues:
            lines.append(f"Verification: {status} ({verification_issues} issues)")
        else:
            lines.append(f"Verification: {status}")
    critique_count = getattr(rs, "paper_critique_issue_count", 0)
    if critique_count:
        lines.append(f"Critique issues: {critique_count}")
    paper_ready = getattr(rs, "paper_ready", None)
    if paper_ready is not None:
        lines.append(f"Paper ready: {'Yes' if paper_ready else 'No'}")
    # Integrity summary: surface fatal/warning counts and per-issue codes so
    # the user can immediately see why paper_ready might be False.
    integrity = getattr(rs, "integrity_report", None) or {}
    if integrity:
        fatal = int(integrity.get("fatal_count", 0) or 0)
        warning = int(integrity.get("warning_count", 0) or 0)
        lines.append(f"Integrity: fatal={fatal}, warning={warning}")
        for issue in integrity.get("issues", []) or []:
            code = issue.get("code", "?")
            severity = issue.get("severity", "?")
            lines.append(f"  [{severity}] {code}")
    if not lines:
        lines.append("No report artifacts yet.")
    return CommandResult(True, "\n".join(lines))


def _cmd_new(state) -> CommandResult:
    if not state.ready:
        return CommandResult(True, "No active session to end.")
    state.reset_session()
    return CommandResult(True, "Session ended. Type a new goal to start fresh.")


def _cmd_approve(state) -> CommandResult:
    rs = getattr(state, "research_state", None)
    if not rs:
        return CommandResult(True, "No research session. Start one first.")
    if getattr(rs, "approval_status", "none") != "pending":
        return CommandResult(True, f"No pending approval (current: {getattr(rs, 'approval_status', 'none')}).")
    rs.approval_status = "approved"
    return CommandResult(True, "__approve__")


def _cmd_reject(state) -> CommandResult:
    rs = getattr(state, "research_state", None)
    if not rs:
        return CommandResult(True, "No research session. Start one first.")
    if getattr(rs, "approval_status", "none") != "pending":
        return CommandResult(True, f"No pending approval (current: {getattr(rs, 'approval_status', 'none')}).")
    rs.approval_status = "rejected"
    return CommandResult(True, "__reject__")


def _cmd_sessions(state) -> CommandResult:
    # Actual listing delegated to caller since it needs config/persistence_root
    return CommandResult(handled=True, output="__list_sessions__")
