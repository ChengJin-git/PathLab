"""Bounded, cooperative budget shutdown; unfinished writing is a checkpoint."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import store
from .recovery import block

GRACE_SECONDS = 120
CHECKPOINT_PROMPT = """The current research budget has been reached. Stop starting experiments,
downloads and computations. This is a recoverable pause, not a completed study.
You have a short checkpoint-only window: finish the current sentence/section boundary,
save completed manuscript sections with save_report_draft (or report-draft.md), and
write what remains in findings.md. Do not generate_article or finish_research, and do
not invent missing content to make a report look complete. Call request_help with
reason budget and blocker external_dependency in the user's language. Include an
attempts entry recording the checked remaining budget and saved checkpoint, and
why_user specifying the additional time/attempts that need authorization. Explain that results and draft are saved,
which sections/experiments remain, and that Continue with added time/attempts resumes
this same session. If this is a data-only task, retain its files/metrics, no manuscript.
End your turn after checkpointing. Do not sleep or poll."""


def expired(session, now=None) -> bool:
    meta = session.recovery_metadata or {}
    start = meta.get("started_at")
    current = time.time() if now is None else now
    suspended = max(0, current - meta['gpu_wait_started_at']) if meta.get('gpu_wait_started_at') else 0
    return bool(
        start
        and current - start - suspended
        >= int(meta.get("time_budget_seconds", 14400))
    )


async def checkpoint_stop(
    session, client, conversation_id, active: bool, messages: list[dict], now=None
) -> bool:
    """Return true only after the session is blocked. Existing jobs retain their state."""
    now = time.time() if now is None else now
    meta = session.recovery_metadata or {}
    if meta.get("finish_requested"):
        return False
    shutdown = meta.get("budget_shutdown")
    if not shutdown and not (
        expired(session, now) or meta.get("budget_stop_requested")
    ):
        return False
    if not shutdown:
        shutdown = {
            "reason": meta.get("budget_stop_requested") or "time",
            "started_at": now,
            "deadline": now + GRACE_SECONDS,
            "phase": meta.get("research_phase", session.phase),
        }
        await store.update(
            session.session_id,
            meta={"budget_shutdown": shutdown, "finish_requested": False},
            event={"kind": "budget_checkpoint", "phase": shutdown["phase"]},
        )
        await client.prompt(conversation_id, CHECKPOINT_PROMPT)
        return False
    if now < shutdown["deadline"] and (active or now - shutdown["started_at"] < 5):
        return False
    if active:
        # Last-resort bound on an unresponsive provider; preserve public partial output.
        await client.interrupt(conversation_id)
    root = Path(session.workspace_path)
    checkpoint = root / "budget-checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "incomplete": True,
                "phase": shutdown["phase"],
                "reason": shutdown["reason"],
                "saved_at": now,
                "instruction": "Resume from saved results and report draft. This is not a final manuscript.",
                "last_assistant_output": [
                    m for m in messages[-10:] if m.get("type") == "assistant"
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    await block(
        session.session_id,
        reason="budget",
        detail=f"Checkpoint saved; {shutdown['reason']} budget reached. Phase: {shutdown['phase']}.",
    )
    return True
