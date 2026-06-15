"""Import Gateway PathScientist file-backed sessions into auto_research_* tables."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.auth.models import User  # noqa: E402
from backend.database.database import safe_session  # noqa: E402
from gateway import pathscientist_persistence  # noqa: E402
from gateway.routes import pathscientist as pathscientist_routes  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import PathScientist gateway_sessions.json/jsonl events into PostgreSQL."
    )
    parser.add_argument(
        "--base-dir",
        default="",
        help="PathScientist base dir. Defaults to resolved PATHSCIENTIST_BASE_DIR.",
    )
    parser.add_argument(
        "--default-user-id",
        default="",
        help="User id for historical sessions without an owner. Defaults to admin user.",
    )
    args = parser.parse_args()

    base_dir = (
        Path(args.base_dir).expanduser().resolve()
        if args.base_dir
        else pathscientist_routes._resolve_pathscientist_base_dir()
    )
    default_user_id = args.default_user_id or await _admin_user_id()
    if not default_user_id:
        print("No --default-user-id provided and no admin user found; nothing imported.")
        return 1

    registry_path = base_dir / pathscientist_routes.GATEWAY_SESSION_REGISTRY
    if not registry_path.exists():
        print(f"No gateway session registry found at {registry_path}")
        return 0

    sessions = _load_registry(registry_path)
    imported = 0
    skipped = 0
    for session in sessions:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            skipped += 1
            continue
        event_path = (
            base_dir
            / pathscientist_routes.GATEWAY_EVENT_DIR
            / pathscientist_routes._safe_session_filename(session_id)
        )
        events = _load_events(event_path)
        conversation_id = str(session.get("conversation_id") or "").strip()
        conversation_dir = _conversation_dir(base_dir, conversation_id)
        if conversation_dir is not None:
            session.setdefault("persistence_dir", str(conversation_dir))
            session.setdefault("resume_available", (conversation_dir / "base_state.json").is_file())
            _merge_conversation_summary(session, conversation_dir)
        if not events and conversation_dir is not None:
            state = session.get("state") if isinstance(session.get("state"), dict) else {}
            summary = state.get("persisted_summary") if isinstance(state.get("persisted_summary"), dict) else {}
            events = _load_openhands_events(pathscientist_routes, conversation_dir, summary)
        try:
            await pathscientist_persistence.import_session_bundle(
                session=session,
                events=events,
                default_user_id=default_user_id,
            )
            imported += 1
        except Exception as exc:
            skipped += 1
            print(f"Skipped {session_id}: {exc}")

    print(
        f"Imported {imported} PathScientist session(s), skipped {skipped}, base_dir={base_dir}"
    )
    return 0


async def _admin_user_id() -> str:
    async with safe_session() as db:
        result = await db.execute(
            select(User).where(User.role == "admin").limit(1)
        )
        user = result.scalar_one_or_none()
        if user is None:
            result = await db.execute(
                select(User).where(User.username == "admin").limit(1)
            )
            user = result.scalar_one_or_none()
        return str(user.id) if user is not None else ""


def _load_registry(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _conversation_dir(base_dir: Path, conversation_id: str) -> Path | None:
    if not conversation_id:
        return None
    try:
        from backend.pathscientist.persistence.layout import get_persistence_root

        root = Path(get_persistence_root(base_dir))
    except Exception:
        root = base_dir / "conversations"
    for candidate in (root / conversation_id, root / conversation_id.replace("-", "")):
        if candidate.is_dir():
            return candidate
    return None


def _merge_conversation_summary(session: dict[str, Any], conversation_dir: Path) -> None:
    try:
        from backend.pathscientist.persistence.history import load_conversation_summary

        summary = load_conversation_summary(conversation_dir)
    except Exception:
        summary = {}
    if not isinstance(summary, dict):
        summary = {}
    state = session.get("state") if isinstance(session.get("state"), dict) else {}
    persisted_summary = state.get("persisted_summary") if isinstance(state.get("persisted_summary"), dict) else {}
    state["persisted_summary"] = {
        **persisted_summary,
        **summary,
        "persistence_dir": str(conversation_dir),
        "resume_available": (conversation_dir / "base_state.json").is_file(),
    }
    if not session.get("question"):
        session["question"] = summary.get("research_question") or ""
    session["state"] = state


def _load_openhands_events(
    route_module,
    conversation_dir: Path,
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        stage_events = route_module._build_persisted_stage_events(
            summary or {"execution_status": "completed"},
            start_seq=1,
        )
        return stage_events + route_module._load_persisted_conversation_events(
            conversation_dir,
            start_seq=len(stage_events) + 1,
        )
    except Exception:
        return []


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
